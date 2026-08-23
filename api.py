import logging
import os
import uuid
from typing import Any

# Imported first, for its import-time side effect: it forces stdout/stderr to
# UTF-8 so the pipeline's progress prints cannot raise UnicodeEncodeError on
# Windows. That exception was killing risk analysis on every run and claim
# verification intermittently -- see console_safety.py for the full write-up.
# This has to happen before any module that prints is imported.
import console_safety  # noqa: F401  (imported for side effect)

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from chatbot import chat_with_document, store_document
from db import add_comment, count_decisions, create_analysis_job, ensure_schema, set_analysis_job_stage, find_similar_companies, get_analysis_job, get_report, get_score_history, list_comments, list_reports, persist_report, record_decision, stats, update_analysis_job
from db import healthcheck as neon_healthcheck
from document_extractor import SUPPORTED_FORMATS, UnsupportedDocument, extract_document, is_supported
from rate_limiter import is_allowed as rate_limit_is_allowed
from structured_extractor import extract_structured
from ventureflow_agent import run_due_diligence

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("ventureflow.api")

MAX_TEXT_CHARS = 50_000
MAX_CLAIMS = 12
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))

app = FastAPI(
    title="VentureFlow AI",
    description="AI-powered VC due diligence platform",
    version="3.0.0",
)
origins = [
    value.strip()
    for value in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if value.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
async def initialize_database_schema() -> None:
    """Bring Neon to the application schema before accepting analysis jobs."""
    try:
        await run_in_threadpool(ensure_schema)
    except Exception:
        # Keep health diagnostics available if Neon is temporarily unreachable.
        # Analysis persistence will still return its existing clear 503 response.
        logger.exception("Neon schema migration unavailable during startup")


@app.on_event("shutdown")
async def close_database_pool() -> None:
    """Release pooled Neon connections cleanly on shutdown."""
    from db import close_pool

    await run_in_threadpool(close_pool)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path in {"/health", "/"}:
        return await call_next(request)
    client = request.client.host if request.client else "unknown"
    if not rate_limit_is_allowed(client, RATE_LIMIT):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please retry in a minute."},
        )
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception):
    logger.exception("Unhandled API error")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "The analysis service encountered an unexpected error. Please retry."
        },
    )


class DiligenceRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=160)
    company_description: str = Field(default="", max_length=MAX_TEXT_CHARS)
    claims: list[str] = Field(default_factory=list, max_length=MAX_CLAIMS)
    filing_text: str = Field(default="", max_length=MAX_TEXT_CHARS)
    revenue: float | None = Field(default=None, ge=0)
    burn_rate: float | None = Field(default=None, ge=0)
    runway_months: float | None = Field(default=None, ge=0, le=600)
    domain: str | None = Field(default=None, max_length=253)
    sector: str | None = Field(default=None, max_length=100)
    team_size: int | None = Field(default=None, ge=0, le=100_000)
    github_url: str | None = Field(default=None, max_length=300)
    founders: list[str] = Field(default_factory=list, max_length=5)

    @field_validator(
        "company_name",
        "company_description",
        "filing_text",
        "domain",
        "sector",
        "github_url",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("claims")
    @classmethod
    def clean_claims(cls, claims: list[str]) -> list[str]:
        cleaned = [claim.strip() for claim in claims if claim and claim.strip()]
        if any(len(claim) > 1_000 for claim in cleaned):
            raise ValueError("Each claim must be 1,000 characters or fewer")
        return cleaned


class DiligenceResponse(BaseModel):
    company: str
    final_score: float
    recommendation: str
    risk_level: str
    ai_analysis: str
    claims_verified: int
    claims_supported: int
    claims_refuted: int
    claims_uncertain: int
    risk_signals_found: int
    key_concerns: list[str]
    red_flags: list[str]
    positive_factors: list[str]
    sections: dict[str, Any] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    similar_companies: list[dict[str, Any]] = Field(default_factory=list)
    incomplete_analysis: bool = False
    # Which mechanism produced final_score: "venturescore_model" when the
    # trained model ran, "legacy_formula_fallback" when it could not be loaded.
    # Declared here because Pydantic drops any key the response model does not
    # know about -- run_due_diligence() has been setting this since the model
    # landed, and it was being silently discarded on the way out of the API,
    # so no caller could tell a model-produced score from the fallback.
    score_source: str | None = None
    # True when claims were extracted and checked but public evidence could
    # not corroborate any of them -- the normal case for an early-stage
    # company nobody has written about yet. Distinct from
    # incomplete_analysis, which means the pipeline itself did not run.
    claims_unverified: bool = False
    report_id: str | None = None
    session_id: str


class AnalysisJobResponse(BaseModel):
    job_id: str
    status: str
    report: DiligenceResponse | None = None
    error: str | None = None
    # The pipeline step currently executing, for honest progress reporting.
    # None for jobs that predate stage tracking, and for queued jobs.
    stage: str | None = None


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2_000)


class ChatResponse(BaseModel):
    answer: str
    confidence: float
    has_data: bool
    sources: list[str]


class DetectedFounder(BaseModel):
    name: str
    role: str = ""
    background: str = ""


class PDFExtractResponse(BaseModel):
    session_id: str
    extracted_text: str
    detected_claims: list[str]
    company_description: str
    revenue: float | None
    runway_months: float | None
    page_count: int
    extraction_method: str = "regex_fallback"
    # Founders read out of the deck itself, so the Founder Analysis tab has an
    # input path at all. The upload form shows these back to the user to
    # correct or add to before the analysis is submitted -- extraction is a
    # starting point, not an authority on who founded the company.
    detected_founders: list[DetectedFounder] = Field(default_factory=list)
    # "PDF" / "PowerPoint" / "Word" / "plain text" / "Markdown". Surfaced so
    # the UI can say which reader ran rather than implying everything is a PDF.
    document_format: str = "PDF"


def _as_list(value: Any) -> list[str]:
    return (
        [str(item) for item in value if item is not None]
        if isinstance(value, list)
        else ([str(value)] if value else [])
    )


def _number(value: Any, default: float = 0) -> float:
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def _normalize_report(report: Any, company_name: str) -> dict[str, Any]:
    report = report if isinstance(report, dict) else {}
    sections = (
        report.get("sections") if isinstance(report.get("sections"), dict) else {}
    )
    claims = sections.get("claims") if isinstance(sections.get("claims"), dict) else {}
    risk = sections.get("risk") if isinstance(sections.get("risk"), dict) else {}
    risk_level = str(
        report.get("risk_level")
        or risk.get("risk_level")
        or risk.get("overall_risk_level")
        or "UNKNOWN"
    )
    claims.update(
        {
            "checked": int(_number(claims.get("checked"))),
            "supported": int(_number(claims.get("supported"))),
            "refuted": int(_number(claims.get("refuted"))),
            "uncertain": int(_number(claims.get("uncertain"))),
            "details": claims.get("details")
            if isinstance(claims.get("details"), list)
            else [],
        }
    )
    risk.update(
        {
            "risk_level": risk_level,
            "overall_score": _number(risk.get("overall_score"), 30),
            "total_signals": int(_number(risk.get("total_signals"))),
            "key_concerns": _as_list(risk.get("key_concerns")),
            "red_flags": _as_list(risk.get("red_flags")),
            "positive_factors": _as_list(risk.get("positive_factors")),
            "ai_reasoning": str(
                risk.get("ai_reasoning")
                or "Risk analysis completed from available evidence."
            ),
        }
    )
    sections.update(
        {
            "claims": claims,
            "risk": risk,
            "ai_analysis": str(
                sections.get("ai_analysis") or report.get("ai_analysis") or ""
            ),
        }
    )
    report.update(
        {
            "company": str(report.get("company") or company_name),
            "sections": sections,
            "final_score": _number(report.get("final_score")),
            "recommendation": str(
                report.get("recommendation") or "NEEDS MORE DILIGENCE"
            ),
            "risk_level": risk_level,
            "data_quality": report.get("data_quality")
            if isinstance(report.get("data_quality"), dict)
            else {},
            "incomplete_analysis": bool(report.get("incomplete_analysis", False)),
        }
    )
    return report


@app.get("/")
def root():
    return {
        "name": "VentureFlow AI",
        "version": "3.0.0",
        "status": "running",
        "endpoints": {
            "analyze": "POST /analyze",
            "upload_pdf": "POST /upload-pdf",
            "chat": "POST /chat",
        },
    }


@app.get("/health")
def health():
    try:
        return {
            "status": "healthy",
            "database": "connected" if neon_healthcheck() else "unavailable",
        }
    except Exception:  # noqa: BLE001 - health must not expose connection failures
        return {"status": "degraded", "database": "unavailable"}


async def _perform_analysis(request: DiligenceRequest, on_stage=None):
    session_id = str(uuid.uuid4())
    similar_companies: list[dict[str, Any]] = []
    try:
        similar_companies = await run_in_threadpool(
            find_similar_companies, request.company_name, request.domain, request.sector
        )
    except Exception:
        logger.warning("Portfolio comparison unavailable", exc_info=True)
    report = await run_in_threadpool(
        run_due_diligence,
        request.company_name,
        request.company_description,
        request.claims,
        request.filing_text,
        request.revenue,
        request.burn_rate,
        request.runway_months,
        request.sector,
        request.team_size,
        request.github_url,
        request.founders,
        on_stage,
    )
    report = _normalize_report(report, request.company_name)
    report["similar_companies"] = similar_companies
    if similar_companies:
        report["sections"]["portfolio_overlap"] = {
            "flag": True,
            "matches": similar_companies,
        }
    try:
        from embeddings import embed_text

        embed_source = request.company_description or request.filing_text or ""
        report_embedding = await run_in_threadpool(embed_text, embed_source) if embed_source else None
    except Exception:
        logger.warning("Report embedding unavailable", exc_info=True)
        report_embedding = None
    # Persist the chat session id INSIDE the report, before saving it.
    #
    # Without this the document-chat panel is permanently dead on every saved
    # report. The chat keys off session_id, `store_document` files the deck
    # text under that id in chat_sessions, but the id was never written into
    # the report -- and _normalize_report, which rebuilds a reloaded report,
    # hardcoded session_id="". So chat worked only in the browser tab that had
    # just run the analysis, and any report opened from the Dashboard showed a
    # permanently disabled "Run analysis first" input, with no indication that
    # the deck text was in fact still sitting in the database.
    report["session_id"] = session_id
    try:
        report_id = await run_in_threadpool(
            persist_report,
            name=request.company_name,
            description=request.company_description,
            sector=request.sector,
            domain=request.domain,
            report=report,
            embedding=report_embedding,
        )
    except Exception as exc:
        logger.exception("Failed to persist completed report")
        raise HTTPException(
            status_code=503,
            detail="Analysis completed but could not be saved. Please retry.",
        ) from exc
    document = request.filing_text or request.company_description
    if document:
        store_document(session_id, document, request.company_name)
    claims, risk = report["sections"]["claims"], report["sections"]["risk"]
    return DiligenceResponse(
        company=report["company"],
        final_score=report["final_score"],
        recommendation=report["recommendation"],
        risk_level=report["risk_level"],
        ai_analysis=report["sections"]["ai_analysis"],
        claims_verified=claims["checked"],
        claims_supported=claims["supported"],
        claims_refuted=claims["refuted"],
        claims_uncertain=claims["uncertain"],
        risk_signals_found=risk["total_signals"],
        key_concerns=risk["key_concerns"],
        red_flags=risk["red_flags"],
        positive_factors=risk["positive_factors"],
        sections=report["sections"],
        data_quality=report["data_quality"],
        similar_companies=similar_companies,
        incomplete_analysis=report["incomplete_analysis"],
        # These two are set by run_due_diligence and were being dropped here.
        # There are two places that build a DiligenceResponse -- this one, for
        # a freshly-run analysis, and _normalize_report for a report reloaded
        # from the database -- and a field added to only one of them silently
        # disappears on whichever path the caller happens to take. That is how
        # score_source ended up reading None on every live run while looking
        # correct on reloaded reports.
        score_source=report.get("score_source"),
        claims_unverified=bool(report.get("claims_unverified")),
        report_id=report_id,
        session_id=session_id,
    )


async def _extract_uploaded_document(
    file: UploadFile, company_name: str
) -> PDFExtractResponse:
    """Shared body of /upload-pdf and /upload-document.

    Every accepted format converges on the same text -> extract_structured
    pipeline (see document_extractor.py). The route stays format-agnostic so
    adding a reader is one entry in that module and nothing here.
    """
    if not is_supported(file.filename or ""):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported formats: {', '.join(sorted(SUPPORTED_FORMATS))}",
        )
    file_bytes = await file.read(10 * 1024 * 1024 + 1)
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=400, detail="File too large. Maximum size is 10MB"
        )
    try:
        document = await run_in_threadpool(
            extract_document, file.filename or "", file_bytes
        )
        text = document["text"]
        if len(text or "") < 50:
            raise HTTPException(
                status_code=422,
                detail=f"Could not extract readable text from this {document['format']} file.",
            )
        info = await run_in_threadpool(extract_structured, text)
        session_id = str(uuid.uuid4())
        store_document(session_id, text, company_name)
        return PDFExtractResponse(
            session_id=session_id,
            extracted_text=text[:5000],
            detected_claims=info.get("claims", [])[:MAX_CLAIMS],
            company_description=info.get("description", ""),
            revenue=info.get("revenue"),
            runway_months=info.get("runway_months"),
            page_count=document["page_count"],
            extraction_method=info.get("_method", "regex_fallback"),
            detected_founders=[
                DetectedFounder(**founder) for founder in (info.get("founders") or [])[:5]
            ],
            document_format=document["format"],
        )
    except HTTPException:
        raise
    except UnsupportedDocument as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Document processing error")
        raise HTTPException(
            status_code=422, detail="The document could not be processed."
        ) from exc


@app.post("/upload-pdf", response_model=PDFExtractResponse)
async def upload_pdf(
    file: UploadFile = File(...),  # noqa: B008 - FastAPI multipart declaration
    company_name: str = Form(default="Unknown Company", max_length=160),
):
    """Kept at its original path because the frontend and scripts/batch_deck_test.py
    both call it; it now accepts every format /upload-document does."""
    return await _extract_uploaded_document(file, company_name)


@app.post("/upload-document", response_model=PDFExtractResponse)
async def upload_document(
    file: UploadFile = File(...),  # noqa: B008 - FastAPI multipart declaration
    company_name: str = Form(default="Unknown Company", max_length=160),
):
    return await _extract_uploaded_document(file, company_name)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    result = await run_in_threadpool(
        chat_with_document, request.session_id, request.question, False
    )
    return ChatResponse(**result)


@app.get("/reports")
def saved_reports():
    try:
        return list_reports()
    except Exception as exc:
        logger.exception("Could not list saved reports")
        raise HTTPException(status_code=503, detail="Saved reports are currently unavailable.") from exc


@app.get("/reports/{report_id}", response_model=DiligenceResponse)
def saved_report(report_id: str):
    try:
        stored = get_report(report_id)
    except Exception as exc:
        logger.exception("Could not load saved report")
        raise HTTPException(status_code=503, detail="Saved report is currently unavailable.") from exc
    if not stored:
        raise HTTPException(status_code=404, detail="Saved report not found.")
    report = _normalize_report(stored.get("raw_output"), stored["company"])
    report["report_id"] = stored["report_id"]
    # Carry the original chat session id through so the document-chat panel
    # keeps working on a reloaded report. This used to be forced to "", which
    # disabled chat on every saved report even though the deck text was still
    # in chat_sessions. Reports written before this change have no stored
    # session id and correctly fall back to "" -- chat stays disabled for
    # those, which is honest rather than broken.
    stored_session = (stored.get("raw_output") or {}).get("session_id") or ""
    claims, risk = report["sections"]["claims"], report["sections"]["risk"]
    return DiligenceResponse(
        company=report["company"], final_score=report["final_score"], recommendation=report["recommendation"],
        risk_level=report["risk_level"], ai_analysis=report["sections"]["ai_analysis"],
        claims_verified=claims["checked"], claims_supported=claims["supported"], claims_refuted=claims["refuted"], claims_uncertain=claims["uncertain"],
        risk_signals_found=risk["total_signals"], key_concerns=risk["key_concerns"], red_flags=risk["red_flags"],
        positive_factors=risk["positive_factors"], sections=report["sections"], data_quality=report["data_quality"],
        similar_companies=report.get("similar_companies", []), incomplete_analysis=report["incomplete_analysis"],
        score_source=report.get("score_source"),
        claims_unverified=bool(report.get("claims_unverified")),
        report_id=report_id, session_id=stored_session,
    )


class DecisionRequest(BaseModel):
    decision: str = Field(pattern="^(invest|pass)$")
    notes: str = Field(default="", max_length=2000)


@app.get("/companies/{company_name}/history")
async def company_score_history(company_name: str):
    """Real historical score data for one company (p2 on the Ship List) --
    powers Dashboard.tsx's score-trend chart once 2+ analyses exist."""
    try:
        history = await run_in_threadpool(get_score_history, company_name)
    except Exception:
        logger.warning("Score history unavailable for %s", company_name, exc_info=True)
        history = []
    return {
        "company": company_name,
        "history": [
            {
                "date": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                "score": row["final_score"],
                "recommendation": row["recommendation"],
            }
            for row in history
        ],
    }


@app.post("/reports/{report_id}/decision")
async def record_report_decision(report_id: str, request: DecisionRequest):
    """Record the user's own invest/pass call on a report. This is the
    feedback signal the firm-personalization ranking layer trains against
    (see ml/personalization.py) -- it accumulates from here, one decision
    at a time, and is worth nothing until there's real usage behind it."""
    try:
        await run_in_threadpool(record_decision, report_id, request.decision, request.notes)
        decided = await run_in_threadpool(count_decisions)
    except Exception as exc:
        logger.exception("Could not record decision for report %s", report_id)
        raise HTTPException(status_code=503, detail="Could not save this decision. Please retry.") from exc
    return {"recorded": True, "total_decisions": decided}


# Export formats. All three render the same `report_document.build_report_blocks()`
# content, so they cannot drift apart -- see report_document.py.
EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "pdf": ("application/pdf", "pdf"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "md": ("text/markdown; charset=utf-8", "md"),
}


async def _render_report_export(report_id: str, fmt: str) -> Response:
    if fmt not in EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported export format. Supported: {', '.join(sorted(EXPORT_FORMATS))}",
        )
    try:
        stored = await run_in_threadpool(get_report, report_id)
    except Exception as exc:
        logger.exception("Could not load report for export")
        raise HTTPException(status_code=503, detail="Saved report is currently unavailable.") from exc
    if not stored:
        raise HTTPException(status_code=404, detail="Saved report not found.")

    import datetime

    report = _normalize_report(stored.get("raw_output"), stored["company"])
    generated_on = datetime.date.today().isoformat()

    try:
        if fmt == "pdf":
            from report_pdf import build_report_pdf
            content: bytes = await run_in_threadpool(build_report_pdf, report, generated_on)
        elif fmt == "docx":
            from report_docx import build_report_docx
            content = await run_in_threadpool(build_report_docx, report, generated_on)
        else:
            from report_markdown import build_report_markdown
            markdown = await run_in_threadpool(build_report_markdown, report, generated_on)
            content = markdown.encode("utf-8")
    except Exception as exc:
        logger.exception("%s generation failed", fmt)
        raise HTTPException(status_code=500, detail=f"Could not generate the {fmt.upper()} export.") from exc

    media_type, extension = EXPORT_FORMATS[fmt]
    safe_name = "".join(c if c.isalnum() else "-" for c in stored["company"]).strip("-").lower() or "ventureflow"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-due-diligence.{extension}"'},
    )


@app.get("/reports/{report_id}/pdf")
async def saved_report_pdf(report_id: str):
    """Kept at its original path -- the frontend links to it directly."""
    return await _render_report_export(report_id, "pdf")


@app.get("/reports/{report_id}/export/{fmt}")
async def saved_report_export(report_id: str, fmt: str):
    """PDF, Word or Markdown, all from the same report content."""
    return await _render_report_export(report_id, fmt.lower())


class CommentRequest(BaseModel):
    author_name: str = Field(default="Anonymous", max_length=80)
    body: str = Field(min_length=1, max_length=4000)


@app.post("/reports/{report_id}/comments")
async def create_comment(report_id: str, request: CommentRequest):
    """No accounts exist yet (Section 3 of the Ship List) -- author_name is
    free text, not a verified identity. This is shared commenting on one
    Neon database, honestly short of real per-user team collaboration."""
    try:
        comment = await run_in_threadpool(add_comment, report_id, request.author_name, request.body)
    except Exception as exc:
        logger.exception("Could not save comment for report %s", report_id)
        raise HTTPException(status_code=503, detail="Could not save this comment. Please retry.") from exc
    return comment


@app.get("/reports/{report_id}/comments")
async def get_comments(report_id: str):
    try:
        return await run_in_threadpool(list_comments, report_id)
    except Exception:
        logger.warning("Comments unavailable for report %s", report_id, exc_info=True)
        return []


def _describe_failure(exc: BaseException) -> str:
    """Turn an exception into something a VC reading the screen can act on.

    The previous version of the failure path stored a fixed string --
    "Analysis could not be completed. Please retry." -- for every possible
    cause, discarding the actual exception. So a rate-limited API key, an
    unreachable database and a genuine bug in the pipeline were
    indistinguishable to the user, and "retry" was actively wrong advice for
    two of the three. This is a due-diligence product; it should never fail
    without saying why.

    Known causes are translated into an action the user can actually take.
    Anything unrecognised falls through to the exception type and message,
    truncated -- which is still far more useful than a fixed string, and keeps
    this function from needing to anticipate every failure mode.
    """
    text = str(exc)
    name = type(exc).__name__

    if "rate_limit_exceeded" in text or "RateLimitError" in name:
        if "tokens per day" in text or "TPD" in text:
            return (
                "The Groq API daily token quota is exhausted, so the AI analysis "
                "steps could not run. This resets every 24 hours, or the tier can "
                "be upgraded at console.groq.com/settings/billing. Retrying now "
                "will fail the same way."
            )
        return (
            "The Groq API rate limit was hit and did not clear after retries. "
            "Wait a minute and retry, or upgrade the API tier for more headroom."
        )
    if "model_not_found" in text or "does not exist or you do not have access" in text:
        return (
            "The configured Groq model is unavailable on this API key. Check the "
            "MODEL constant in groq_client.py against the models the key can actually reach."
        )
    if "AuthenticationError" in name or "invalid_api_key" in text:
        return "The Groq API key was rejected. Check GROQ_API_KEY in .env."
    if "OperationalError" in name or "could not translate host name" in text or "connection" in text.lower():
        return (
            "The database could not be reached while saving this analysis. "
            "Check DATABASE_URL in .env and that the Neon project is not paused."
        )
    if "APITimeoutError" in name or "timeout" in text.lower():
        return (
            "An external call timed out during analysis (LLM or web search). "
            "This is usually transient -- retrying often works."
        )
    return f"Analysis failed: {name}: {text[:300]}"


async def _run_analysis_job(job_id: str, request_data: dict[str, Any]) -> None:
    try:
        await run_in_threadpool(update_analysis_job, job_id, "running")

        # Real progress, written from the pipeline as it advances. The
        # frontend polls this instead of advancing labels on a fixed timer,
        # so a slow-but-working analysis is distinguishable from a hung one.
        # run_due_diligence executes in a worker thread, so this callback is
        # invoked from that thread -- set_analysis_job_stage opens its own
        # short-lived connection rather than sharing one, which keeps that
        # safe.
        def record_stage(label: str) -> None:
            set_analysis_job_stage(job_id, label)

        report = await _perform_analysis(
            DiligenceRequest(**request_data), on_stage=record_stage
        )
        await run_in_threadpool(update_analysis_job, job_id, "complete", report.model_dump())
    except Exception as exc:
        logger.exception("Analysis job %s failed", job_id)
        message = _describe_failure(exc)
        try:
            await run_in_threadpool(
                update_analysis_job, job_id, "failed", None, message,
            )
        except Exception:
            # If even recording the failure fails, the job would sit in
            # "running" forever and the frontend would poll indefinitely.
            logger.exception("Could not mark analysis job %s as failed", job_id)


@app.post("/analyze", response_model=AnalysisJobResponse, status_code=202)
async def analyze_company(request: DiligenceRequest, background_tasks: BackgroundTasks):
    try:
        job_id = await run_in_threadpool(create_analysis_job, request.model_dump())
    except Exception as exc:
        logger.exception("Could not create analysis job")
        raise HTTPException(status_code=503, detail="Analysis queue is currently unavailable.") from exc
    background_tasks.add_task(_run_analysis_job, job_id, request.model_dump())
    return AnalysisJobResponse(job_id=job_id, status="pending")


@app.get("/analyze/status/{job_id}", response_model=AnalysisJobResponse)
async def analysis_status(job_id: str):
    try:
        job = await run_in_threadpool(get_analysis_job, job_id)
    except Exception as exc:
        logger.exception("Could not load analysis job status")
        raise HTTPException(status_code=503, detail="Analysis status is currently unavailable.") from exc
    if not job:
        raise HTTPException(status_code=404, detail="Analysis job not found.")
    report = DiligenceResponse(**job["result"]) if job["status"] == "complete" and job.get("result") else None
    return AnalysisJobResponse(job_id=job["job_id"], status=job["status"], report=report, error=job.get("error_message"), stage=job.get("stage"))


@app.get("/database/stats")
def database_stats():
    try:
        return stats()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Database statistics are currently unavailable."
        ) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False)
