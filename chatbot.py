import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json
import logging
from rag_engine import build_context, format_context_for_llm
from groq_client import MODEL, get_client

logger = logging.getLogger(__name__)

# In-process cache for document context per session, backed by the
# `chat_sessions` Neon table (migrations/004_chat_sessions.sql) so a session
# survives a server restart. The DB write is best-effort: if Neon isn't
# configured or is briefly unreachable, chat still works for the lifetime of
# this process -- it just won't survive a restart, same as before.
_document_store = {}


def _persist_session(session_id: str, entry: dict) -> None:
    try:
        from db import upsert_chat_session
        upsert_chat_session(session_id, entry["company"], entry["text"], entry["history"])
    except Exception as exc:
        logger.warning("Chat session %s not persisted to DB (in-memory only): %s", session_id, exc)


def store_document(session_id: str, text: str, company_name: str):
    """Store extracted document text for a session, in-memory and in Neon."""
    entry = {
        "text":    text[:15000],  # cap at 15K chars
        "company": company_name,
        "history": [],
    }
    _document_store[session_id] = entry
    _persist_session(session_id, entry)

def get_document(session_id: str) -> dict:
    entry = _document_store.get(session_id)
    if entry is not None:
        return entry
    # Not cached in this process (e.g. after a restart) -- fall back to Neon.
    try:
        from db import get_chat_session
        row = get_chat_session(session_id)
    except Exception as exc:
        logger.warning("Chat session %s DB lookup unavailable: %s", session_id, exc)
        return None
    if not row:
        return None
    entry = {
        "text":    row["document_text"],
        "company": row["company"],
        "history": row["history"] or [],
    }
    _document_store[session_id] = entry
    return entry

def clear_document(session_id: str):
    _document_store.pop(session_id, None)
    try:
        from db import delete_chat_session
        delete_chat_session(session_id)
    except Exception as exc:
        logger.warning("Chat session %s DB delete unavailable: %s", session_id, exc)

def chat_with_document(
    session_id: str,
    question: str,
    verbose: bool = True,
) -> dict:
    """
    Answer a question about the uploaded document.
    Uses both the document text AND Neon database evidence.
    Returns NOT_ENOUGH_INFO if evidence is insufficient.
    """
    doc = get_document(session_id)
    if not doc:
        return {
            "answer":     "No document found for this session. Please upload a document first.",
            "confidence": 0.0,
            "sources":    [],
            "has_data":   False,
        }

    document_text = doc["text"]
    company_name  = doc["company"]
    history       = doc["history"]

    if verbose:
        print(f"  Chatbot question: {question[:80]}...")

    # Get relevant context from the Neon database (rag_engine.py -> db.py)
    try:
        rag_context       = build_context(f"{company_name} {question}")
        db_context        = format_context_for_llm(rag_context)
    except Exception as e:
        print(f"  RAG error: {e}")
        db_context = "Database context unavailable"

    # Build conversation history for context
    history_text = ""
    if history:
        history_text = "PREVIOUS CONVERSATION:\n"
        for turn in history[-4:]:  # last 4 exchanges
            history_text += f"Q: {turn['question']}\n"
            history_text += f"A: {turn['answer']}\n\n"

    prompt = f"""You are a strict VC due diligence assistant.
You ONLY answer questions using information explicitly present in the provided document.

PITCH DECK:
{document_text[:8000]}

FINANCIAL DATABASE EVIDENCE:
{db_context}

{history_text}

QUESTION: {question}

STRICT RULES — these are non-negotiable:
1. If the answer is not in the document, respond EXACTLY with:
   "I don't have enough information in this document to answer that."
2. Never add information from your general knowledge about the company
3. Always quote the specific part of the document that supports your answer
4. If you're estimating or inferring, say "Based on the document, it appears..."
5. Numbers must match exactly what's in the document — never round or adjust
6. If asked about something not in the document (e.g. exit strategy, future plans
   not mentioned), say you don't have that information

Answer (cite document section if possible):"""

    try:
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a precise VC analyst. Answer only from provided evidence. "
                        "Say 'I don't have enough information' when the answer isn't in the document. "
                        "Never hallucinate numbers or facts."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,  # very low for factual accuracy
            max_tokens=500,
        )

        answer = response.choices[0].message.content.strip()

        # Detect "not enough info" responses
        not_enough_phrases = [
            "don't have enough information",
            "not in the document",
            "not mentioned",
            "cannot find",
            "no information",
            "not provided",
            "not specified",
        ]
        has_data = not any(
            phrase in answer.lower()
            for phrase in not_enough_phrases
        )

        # Store in history
        history.append({
            "question": question,
            "answer":   answer,
        })
        doc["history"] = history[-10:]  # keep last 10 turns
        _persist_session(session_id, doc)

        result = {
            "answer":     answer,
            "confidence": 0.9 if has_data else 0.1,
            "has_data":   has_data,
            "sources":    ["pitch_deck", "neon_database"],
        }

        if verbose:
            print(f"  Answer: {answer[:100]}...")
            print(f"  Has data: {has_data}")

        return result

    except Exception as e:
        print(f"  Chatbot error: {e}")
        return {
            "answer":     f"Error processing question: {e}",
            "confidence": 0.0,
            "has_data":   False,
            "sources":    [],
        }

if __name__ == "__main__":
    # Test chatbot
    session_id = "test_session"
    sample_doc = """
    NovaMed AI is a Series A HealthTech company.
    We have $2.5M ARR growing 18% MoM.
    Our FDA-cleared AI diagnostics platform has 14M records.
    Founders: Dr. Priya Sharma (CEO, ex-Stanford Medicine) and Marcus Wei (CTO, ex-Google Health).
    We are raising $12M at a $68M pre-money valuation.
    Our runway is 18 months.
    Top 3 clients represent 64% of ARR.
    """

    store_document(session_id, sample_doc, "NovaMed AI")

    questions = [
        "What is the ARR of this company?",
        "Who are the founders?",
        "What is the valuation?",
        "What are the main risks?",
        "What is the company's exit strategy?",  # not in doc
    ]

    for q in questions:
        result = chat_with_document(session_id, q)
        print(f"\nQ: {q}")
        print(f"A: {result['answer']}")
        print(f"Confidence: {result['confidence']}")
        print(f"Has data: {result['has_data']}")