import logging
import os
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from chatbot import chat_with_document, store_document
from db import add_comment, count_decisions, create_analysis_job, ensure_schema, find_similar_companies, get_analysis_job, get_report, get_score_history, list_comments, list_reports, persist_report, record_decision, stats, update_analysis_job
from db import healthcheck as neon_healthcheck
from pdf_extractor import extract_text_from_pdf
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
    report_id: str | None = None
    session_id: str


class AnalysisJobResponse(BaseModel):
    job_id: str
    status: str
    report: DiligenceResponse | None = None
    error: str | None = None


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2_000)


class ChatResponse(BaseModel):
    answer: str
    confidence: float
    has_data: bool
    sources: list[str]


class PDFExtractResponse(BaseModel):
    session_id: str
    extracted_text: str
    detected_claims: list[str]
    company_description: str
    revenue: float | None
    runway_months: float | None
    page_count: int
    extraction_method: str = "regex_fallback"


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


async def _perform_analysis(request: DiligenceRequest):
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
        report_id=report_id,
        session_id=session_id,
    )


@app.post("/upload-pdf", response_model=PDFExtractResponse)
async def upload_pdf(
    file: UploadFile = File(...),  # noqa: B008 - FastAPI multipart declaration
    company_name: str = Form(default="Unknown Company", max_length=160),
):
    if file.content_type not in {"application/pdf", "application/x-pdf"} and not (
        file.filename or ""
    ).lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    file_bytes = await file.read(10 * 1024 * 1024 + 1)
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=400, detail="File too large. Maximum size is 10MB"
        )
    try:
        text = await run_in_threadpool(extract_text_from_pdf, file_bytes)
        if len(text or "") < 50:
            raise HTTPException(
                status_code=422, detail="Could not extract readable text from this PDF."
            )
        info = await run_in_threadpool(extract_structured, text)
        session_id = str(uuid.uuid4())
        store_document(session_id, text, company_name)
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)
        return PDFExtractResponse(
            session_id=session_id,
            extracted_text=text[:5000],
            detected_claims=info.get("claims", [])[:MAX_CLAIMS],
            company_description=info.get("description", ""),
            revenue=info.get("revenue"),
            runway_months=info.get("runway_months"),
            page_count=page_count,
            extraction_method=info.get("_method", "regex_fallback"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PDF processing error")
        raise HTTPException(
            status_code=422, detail="The PDF could not be processed."
        ) from exc


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
    report["session_id"] = ""
    claims, risk = report["sections"]["claims"], report["sections"]["risk"]
    return DiligenceResponse(
        company=report["company"], final_score=report["final_score"], recommendation=report["recommendation"],
        risk_level=report["risk_level"], ai_analysis=report["sections"]["ai_analysis"],
        claims_verified=claims["checked"], claims_supported=claims["supported"], claims_refuted=claims["refuted"], claims_uncertain=claims["uncertain"],
        risk_signals_found=risk["total_signals"], key_concerns=risk["key_concerns"], red_flags=risk["red_flags"],
        positive_factors=risk["positive_factors"], sections=report["sections"], data_quality=report["data_quality"],
        similar_companies=report.get("similar_companies", []), incomplete_analysis=report["incomplete_analysis"],
        report_id=report_id, session_id="",
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


@app.get("/reports/{report_id}/pdf")
async def saved_report_pdf(report_id: str):
    """A real PDF, not the frontend's plain-text export -- see report_pdf.py."""
    try:
        stored = await run_in_threadpool(get_report, report_id)
    except Exception as exc:
        logger.exception("Could not load report for PDF export")
        raise HTTPException(status_code=503, detail="Saved report is currently unavailable.") from exc
    if not stored:
        raise HTTPException(status_code=404, detail="Saved report not found.")

    import datetime

    from report_pdf import build_report_pdf

    report = _normalize_report(stored.get("raw_output"), stored["company"])
    try:
        pdf_bytes = await run_in_threadpool(
            build_report_pdf, report, datetime.date.today().isoformat()
        )
    except Exception as exc:
        logger.exception("PDF generation failed")
        raise HTTPException(status_code=500, detail="Could not generate the PDF.") from exc

    safe_name = "".join(c if c.isalnum() else "-" for c in stored["company"]).strip("-").lower() or "ventureflow"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-due-diligence.pdf"'},
    )


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


async def _run_analysis_job(job_id: str, request_data: dict[str, Any]) -> None:
    try:
        await run_in_threadpool(update_analysis_job, job_id, "running")
        report = await _perform_analysis(DiligenceRequest(**request_data))
        await run_in_threadpool(update_analysis_job, job_id, "complete", report.model_dump())
    except Exception:
        logger.exception("Analysis job %s failed", job_id)
        try:
            await run_in_threadpool(
                update_analysis_job, job_id, "failed", None,
                "Analysis could not be completed. Please retry.",
            )
        except Exception:
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
    return AnalysisJobResponse(job_id=job["job_id"], status=job["status"], report=report, error=job.get("error_message"))


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
