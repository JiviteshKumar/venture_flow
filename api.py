import logging
import os
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from chatbot import chat_with_document, store_document
from db import ensure_schema, find_similar_companies, persist_report, stats
from db import healthcheck as neon_healthcheck
from pdf_extractor import (
    extract_claims_from_text,
    extract_company_info,
    extract_text_from_pdf,
)
from ventureflow_agent import run_due_diligence

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("ventureflow.api")

MAX_TEXT_CHARS = 50_000
MAX_CLAIMS = 12
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
request_windows: dict[str, deque[float]] = defaultdict(deque)

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
    now = time.monotonic()
    window = request_windows[client]
    while window and now - window[0] >= 60:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please retry in a minute."},
        )
    window.append(now)
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

    @field_validator(
        "company_name",
        "company_description",
        "filing_text",
        "domain",
        "sector",
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
    report_id: str | None = None
    session_id: str


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


@app.post("/analyze", response_model=DiligenceResponse)
async def analyze_company(request: DiligenceRequest):
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
    )
    report = _normalize_report(report, request.company_name)
    report["similar_companies"] = similar_companies
    if similar_companies:
        report["sections"]["portfolio_overlap"] = {
            "flag": True,
            "matches": similar_companies,
        }
    try:
        report_id = await run_in_threadpool(
            persist_report,
            name=request.company_name,
            description=request.company_description,
            sector=request.sector,
            domain=request.domain,
            report=report,
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
        info = extract_company_info(text)
        session_id = str(uuid.uuid4())
        store_document(session_id, text, company_name)
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)
        return PDFExtractResponse(
            session_id=session_id,
            extracted_text=text[:5000],
            detected_claims=extract_claims_from_text(text)[:MAX_CLAIMS],
            company_description=info.get("description", ""),
            revenue=info.get("revenue"),
            runway_months=info.get("runway_months"),
            page_count=page_count,
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
