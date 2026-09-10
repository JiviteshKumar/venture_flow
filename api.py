import functools
import logging
import os
import re
import secrets
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Imported first, for its import-time side effect: it forces stdout/stderr to
# UTF-8 so the pipeline's progress prints cannot raise UnicodeEncodeError on
# Windows. That exception was killing risk analysis on every run and claim
# verification intermittently -- see console_safety.py for the full write-up.
# This has to happen before any module that prints is imported.
import console_safety  # noqa: F401  (imported for side effect)
import auth
from company_name import clean as clean_company_name
from chatbot import chat_with_document, store_document
from config_check import check_configuration
from config_check import enforce as enforce_configuration
from db import (
    UserAlreadyExists,
    add_comment,
    count_users,
    create_session,
    create_user,
    delete_expired_sessions,
    delete_session,
    get_session_user,
    get_user_by_email,
    count_active_jobs,
    count_decisions,
    create_analysis_job,
    ensure_schema,
    find_similar_companies,
    get_analysis_job,
    get_report,
    get_score_history,
    list_comments,
    list_reports,
    persist_report,
    reclaim_orphaned_jobs,
    record_analysed_company,
    record_decision,
    set_analysis_job_stage,
    stats,
    update_analysis_job,
)
from db import healthcheck as neon_healthcheck
from document_extractor import (
    SUPPORTED_FORMATS,
    UnsupportedDocument,
    extract_document,
    is_supported,
)
from rate_limiter import is_allowed as rate_limit_is_allowed
import extraction_coverage
import ocr_extractor
import pdf_extractor
import tech_scope
from structured_extractor import extract_structured
from ventureflow_agent import run_due_diligence

load_dotenv()
import observability

# Structured logging BEFORE anything else logs, so no line escapes in plain
# text. Replaces logging.basicConfig, which produced unqueryable stdout -- the
# format every bug in the last three sessions had to be found by reading.
observability.configure_logging()
observability.init_sentry()
logger = logging.getLogger("ventureflow.api")

MAX_TEXT_CHARS = 50_000
MAX_CLAIMS = 12
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
# Trust X-Forwarded-For when running behind a managed platform's load
# balancer (Render, Vercel, Fly). Off by default because the header is
# client-supplied and spoofable when the app is directly internet-facing.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in {"1", "true", "yes"}

app = FastAPI(
    title="VentureFlow AI",
    description="AI-powered VC due diligence platform",
    version="3.0.0",
)
# Both spellings of the dev origin, deliberately. `localhost` and `127.0.0.1`
# are different origins to a browser, and Vite happily serves on either: it
# prints "Local: http://localhost:5173/" but answers on 127.0.0.1:5173 too. A
# default listing only the first means anyone who types the numeric form gets
# a CORS failure whose symptom is "the page loads and nothing ever populates" --
# no error in the server log, because the request never arrives. Confirmed by
# curl before this was widened: an Origin of http://127.0.0.1:5173 came back
# with no Access-Control-Allow-Origin header at all.
DEFAULT_DEV_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
origins = [
    value.strip()
    for value in os.getenv("ALLOWED_ORIGINS", DEFAULT_DEV_ORIGINS).split(",")
    if value.strip()
]

# Optional regex of additional allowed origins, for hosts whose name is not
# fixed. Vercel mints a new hostname per project and per preview deployment
# -- venture-flow-w8hf.vercel.app and venture-flow-livid.vercel.app are two
# live frontends of this same app -- so an exact-match list silently breaks
# every time a new one appears. The symptom is total and unmistakable once you
# know it: every call from the new host fails CORS, the browser reports
# "Network Error", and the server logs a perfectly healthy 200 for a response
# the browser then discards.
#
# Deliberately opt-in with no default. This API has no authentication, so CORS
# is the only thing stopping a page on someone else's domain from spending the
# owner's Groq quota and writing to their database; a regex baked in here would
# widen that for everyone who deploys this. Set it per deployment, and keep it
# anchored -- `^https://venture-flow-[a-z0-9-]+\.vercel\.app$`, never a bare
# `.*vercel\.app`.
ALLOWED_ORIGIN_REGEX = os.getenv("ALLOWED_ORIGIN_REGEX", "").strip() or None
_origin_pattern = re.compile(ALLOWED_ORIGIN_REGEX) if ALLOWED_ORIGIN_REGEX else None

# Shared passphrase gating the deployed demo.
#
# This is a gate, NOT authentication, and the difference is worth being precise
# about because it would be easy to mistake one for the other. There is no user
# model, no per-account data isolation, and no schema-level ownership: every
# report still lives in one shared pool. What this does is stop an anonymous
# passer-by from reading that pool.
#
# It exists because the deployed API had none of the above and was returning
# every uploaded deck's analysis -- company names, scores, and the full memo --
# to any unauthenticated caller, over sequential integer ids (/reports/50) that
# make the whole table trivially enumerable. For a product whose premise is
# confidential diligence on other people's companies, that is the most severe
# defect in the system, and it needed closing before the schema work that will
# eventually replace it.
#
# A public single-page app cannot hold a secret, so the token is not baked into
# the bundle: the user types the passphrase, the frontend keeps it for the tab's
# lifetime and sends it on every request. Anyone you share it with gets in,
# which is exactly the security property of a demo passphrase and no more.
#
# Unset means open, so a fresh clone and local development are unaffected. A
# loud startup warning covers the case that matters -- deployed, reachable from
# a real origin, and ungated.
DEMO_ACCESS_TOKEN = os.getenv("DEMO_ACCESS_TOKEN", "").strip() or None

# Reachable without the passphrase. `/` and `/health` are how a platform health
# check and a human both establish the service is alive, and neither exposes
# any report data. The OpenAPI routes are listed so the docs page can load its
# own schema.
PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc",
                "/auth/register", "/auth/login", "/auth/logout", "/auth/me"}


def _client_key(request: Request) -> str:
    """Identify the caller for rate limiting, correctly behind a proxy.

    `request.client.host` is the peer socket address. On Render (and any
    platform that terminates TLS at a load balancer) that is the *proxy*, not
    the user, so every visitor shares a single 30-requests-per-minute bucket
    and the limiter trips far sooner than intended -- for reasons that look
    nothing like rate limiting from the browser, because the 429 was also
    arriving without CORS headers.

    `X-Forwarded-For` is a client-supplied header and trivially spoofable, so
    it is trusted only when `TRUST_PROXY_HEADERS` is set, which should be true
    on a managed host and false when the app is directly internet-facing.
    Render, Vercel and Fly all set this header; the left-most entry is the
    original client.
    """
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _cors_headers_for(request: Request) -> dict[str, str]:
    """CORS headers for a response that will not pass through CORSMiddleware.

    Two response paths in this app are emitted *outside* that middleware and so
    would otherwise carry no `Access-Control-Allow-Origin` at all:

      * the 429 from the rate-limit middleware, and
      * the 500 from the catch-all exception handler, which Starlette serves
        from ServerErrorMiddleware -- the outermost layer of the whole stack,
        outside anything `add_middleware` can wrap.

    A browser discards a cross-origin response with no ACAO header before any
    JavaScript can read it, so axios reports a bare `Network Error` with no
    status and no body. That is exactly the symptom this app showed in
    production: every underlying failure -- an exhausted rate limit, a Neon
    connection dropping mid-request -- surfaced as the same uninformative
    "Network Error", because the real message never reached the browser.

    It is invisible locally, which is why it survived: `vite.config.ts` proxies
    /api to the backend, making local requests same-origin, and CORS never
    applies at all.

    Mirrors CORSMiddleware's own behaviour: echo the origin only if it is
    allowed, and never reflect an arbitrary one.
    """
    origin = request.headers.get("origin")
    if not origin:
        return {}
    if "*" in origins:
        return {"Access-Control-Allow-Origin": "*"}
    if origin in origins or (_origin_pattern and _origin_pattern.fullmatch(origin)):
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {}


AUTH_COOKIE = "vf_session"

# Key under which an analysis job carries its owner.
#
# Deliberately NOT a field on DiligenceRequest: a client that could name the
# owner of a report could claim someone else's. It rides in the job envelope
# instead and is popped before the request model is built.
OWNER_KEY = "_owner_user_id"


def _bearer_token(request: Request) -> str | None:
    """The session token a caller presented.

    Two accepted forms, for the same reason `_presented_token` accepts two: the
    browser sends `Authorization: Bearer`, and `X-VF-Session` exists so a script
    can authenticate without colliding with the demo passphrase, which also uses
    the Authorization header.
    """
    explicit = request.headers.get("x-vf-session")
    if explicit:
        return explicit.strip()
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def current_user(request: Request) -> dict[str, Any] | None:
    """The signed-in account, or None. Never raises.

    Returns None rather than 401 because most endpoints stay reachable without
    an account -- this deployment has always been usable unauthenticated, and
    turning that off wholesale would break every existing script. What signing
    in changes is OWNERSHIP: an authenticated analysis is scoped to its owner,
    and an anonymous one is visible to everyone, exactly as before.
    """
    token = _bearer_token(request)
    if not token:
        return None
    try:
        return await run_in_threadpool(get_session_user, auth.hash_token(token))
    except Exception:
        # A database that is down must not turn every request into a 500 on the
        # authentication path; it degrades to "not signed in".
        logger.warning("Session lookup failed", exc_info=True)
        return None


async def require_user(request: Request) -> dict[str, Any]:
    """As `current_user`, but 401 when there is nobody signed in."""
    user = await current_user(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Sign in to continue.",
        )
    return user


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)
    display_name: str = Field(default="", max_length=80)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class AuthResponse(BaseModel):
    token: str
    user: dict
    expires_at: str


def _presented_token(request: Request) -> str | None:
    """The passphrase the caller presented, from either accepted form.

    `X-Demo-Token` is what the frontend sends. `Authorization: Bearer` is
    accepted too so the API stays usable from curl and scripts without a
    bespoke header, which matters because `scripts/batch_deck_test.py` and the
    eval harnesses drive these endpoints directly.
    """
    header = request.headers.get("x-demo-token")
    if header:
        return header.strip()
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


# Registered BEFORE CORSMiddleware, deliberately -- see the rate limiter below
# for why that ordering matters. A 401 that reaches a browser without CORS
# headers is discarded before JavaScript can read it, and the frontend would
# show "Network Error" instead of prompting for the passphrase.
@app.middleware("http")
async def require_demo_token(request: Request, call_next):
    if DEMO_ACCESS_TOKEN is None or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    # A CORS preflight carries no custom headers by definition, so it can never
    # present the token. Rejecting it would make the browser report a CORS
    # failure rather than a 401, hiding the real reason from the user.
    if request.method == "OPTIONS":
        return await call_next(request)
    # An account is a stronger credential than the shared passphrase, so a
    # signed-in caller passes this gate without knowing it. Without this, adding
    # accounts to a passphrase-protected deployment would lock every new user
    # out of the sign-in endpoint they need in order to become a user.
    if request.url.path.startswith("/auth/"):
        return await call_next(request)
    presented = _presented_token(request)
    if presented is not None:
        try:
            if await run_in_threadpool(get_session_user, auth.hash_token(presented)):
                return await call_next(request)
        except Exception:
            logger.warning("Session check failed inside the demo gate", exc_info=True)
    if presented is None or not secrets.compare_digest(presented, DEMO_ACCESS_TOKEN):
        return JSONResponse(
            status_code=401,
            content={"detail": "This demo is passphrase-protected. Enter the access passphrase to continue."},
            headers=_cors_headers_for(request),
        )
    return await call_next(request)


# Registered BEFORE CORSMiddleware, deliberately. Starlette applies middleware
# outermost-last, so whatever is added last wraps everything added before it.
# This used to be declared after the CORS middleware, which put the rate
# limiter *outside* it and meant its 429 never got CORS headers. Adding it
# first puts CORS on the outside, where it can decorate the 429 on the way out.
@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path in {"/health", "/"}:
        return await call_next(request)
    if not rate_limit_is_allowed(_client_key(request), RATE_LIMIT):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please retry in a minute."},
            # Belt and braces: correct even if this is ever re-registered in a
            # position CORSMiddleware does not wrap.
            headers=_cors_headers_for(request),
        )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    # Every custom header the frontend sends must be listed here, or the
    # browser's preflight for it is refused with a 400 before the real request
    # is ever made -- which surfaces as an opaque CORS error rather than as the
    # status that would have explained the problem.
    #
    # This has now bitten twice. First with X-Demo-Token, where the symptom was
    # a CORS failure instead of the 401 telling the user to enter the
    # passphrase. Then with Authorization, when accounts landed: adding a
    # bearer token to every request makes every request preflighted, and with
    # Authorization unlisted the dashboard's own /reports call failed with
    # "Response to preflight request doesn't pass access control check" on a
    # user who had just successfully signed in.
    #
    # Caught by tests/test_demo_gate.py::test_preflight_is_not_gated and
    # tests/test_auth.py.
    allow_headers=["Content-Type", "X-Demo-Token", "Authorization", "X-VF-Session"],
)


@app.on_event("startup")
def current_config_report():
    """The configuration check, evaluated against this process's live settings."""
    return check_configuration(
        origins=origins,
        allowed_origin_regex=ALLOWED_ORIGIN_REGEX,
        demo_access_token=DEMO_ACCESS_TOKEN,
    )


async def warn_if_deployed_and_ungated() -> None:
    """Say something loud if this looks deployed but has no passphrase.

    The failure this guards against already happened: the API ran in
    production returning every stored report to anonymous callers, and nothing
    anywhere said so. `ALLOWED_ORIGINS` naming a non-localhost origin is a
    decent proxy for "this is reachable from a real frontend", and combined
    with no DEMO_ACCESS_TOKEN that is the state worth shouting about.
    """
    deployed = any(
        not (o.startswith("http://localhost") or o.startswith("http://127.0.0.1"))
        for o in origins
    ) or bool(ALLOWED_ORIGIN_REGEX)
    if deployed and DEMO_ACCESS_TOKEN is None:
        logger.warning(
            "UNGATED: this API is configured for a non-local origin but "
            "DEMO_ACCESS_TOKEN is not set. Every stored report is readable by "
            "any anonymous caller, and report ids are sequential integers. Set "
            "DEMO_ACCESS_TOKEN to gate it."
        )

    # The full check, covering every variable production needs rather than this
    # one case. Logs each problem at CRITICAL, and raises when STRICT_CONFIG is
    # set. The warning above is kept because it names the specific failure this
    # deployment actually suffered.
    enforce_configuration(current_config_report())


async def _reclaim_jobs_lost_to_the_last_restart() -> None:
    """Every in-flight analysis dies when this process does.

    BackgroundTasks live in the API process and nowhere else, so a Render
    restart -- idle spin-down, deploy, OOM -- kills every running analysis while
    its row still says 'running'. Without this, those rows stay that way
    forever and the frontend polls a spinner that can never resolve. Running it
    at startup is what makes a restart recoverable rather than permanent.

    Best-effort: a failure here must not stop the API booting, because an API
    that will not start is strictly worse than one with a few stale job rows.
    """
    try:
        reclaimed = await run_in_threadpool(reclaim_orphaned_jobs)
        if reclaimed:
            logger.warning(
                "Startup reclaimed %s job(s) orphaned by a previous restart", len(reclaimed),
            )
    except Exception:
        logger.exception("Could not reclaim orphaned analysis jobs at startup")


@app.on_event("startup")
async def initialize_database_schema() -> None:
    """Bring Neon to the application schema before accepting analysis jobs.

    Registered BEFORE the orphan reclamation below, and that ordering matters:
    reclamation writes to analysis_jobs, so on a database that has never been
    migrated it would fail against a table that does not exist yet. FastAPI runs
    startup handlers in registration order.
    """
    try:
        await run_in_threadpool(ensure_schema)
    except Exception:
        # Keep health diagnostics available if Neon is temporarily unreachable.
        # Analysis persistence will still return its existing clear 503 response.
        logger.exception("Neon schema migration unavailable during startup")


@app.on_event("startup")
async def reclaim_orphaned_jobs_at_startup() -> None:
    await _reclaim_jobs_lost_to_the_last_restart()


@app.on_event("shutdown")
async def close_database_pool() -> None:
    """Release pooled Neon connections cleanly on shutdown."""
    from db import close_pool

    await run_in_threadpool(close_pool)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("Unhandled API error")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "The analysis service encountered an unexpected error. Please retry."
        },
        # Starlette serves this from ServerErrorMiddleware, which sits outside
        # every `add_middleware` layer including CORS. Without these headers a
        # browser drops the response and the frontend can only say "Network
        # Error" -- so a genuine 500 became indistinguishable from the backend
        # being down. See _cors_headers_for().
        headers=_cors_headers_for(request),
    )


class DiligenceRequest(BaseModel):
    # Reject unknown fields instead of silently dropping them.
    #
    # Pydantic's default is to ignore an unrecognised key, and the specific way
    # that bites here is nasty: the pipeline function this model feeds takes a
    # parameter named `claims_to_verify`, while the API field is `claims`. A
    # client using the internal name -- an entirely reasonable mistake, and one
    # made while writing this session's own tests -- got a 202, a job id, and a
    # completed analysis that had verified ZERO claims, with nothing anywhere
    # reporting a problem.
    #
    # Silently analysing something other than what was submitted is worse than
    # refusing the request. The frontend sends exactly the fields declared
    # below (see apiClient.startAnalysis), so forbidding extras breaks no
    # existing caller and turns that failure into a 422 naming the bad field.
    model_config = ConfigDict(extra="forbid")

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
    # Per-slide text, so extraction coverage can be measured at the granularity
    # the failure actually occurs at: whole slides contributing nothing.
    # `filing_text` is the pages joined with newlines, which destroys the
    # boundaries -- and without them coverage collapses to a single "slide"
    # that is either 0% or 100% and says nothing useful. Optional: an older
    # client that omits it still gets line-level coverage, just not the
    # slide-level headline.
    deck_slides: list[str] = Field(default_factory=list, max_length=300)
    # Which extraction path produced `claims`/`founders`. Carried so the report
    # can tell its reader when it was built by the degraded regex fallback --
    # see run_due_diligence's extraction_provenance block.
    extraction_method: str = Field(default="", max_length=40)
    extraction_fallback_reason: str = Field(default="", max_length=500)
    # Funding stage. Measured as the single largest lever the score model has:
    # sweeping it across Seed/Early/Growth moves the score 42 points, against 24
    # for industry and 25 for the entire text. It was hardcoded to None in
    # ventureflow_agent, so that range was permanently unused and every deck
    # landed in a 9-point band.
    #
    # Free text rather than an enum: the model's encoder was fitted with
    # handle_unknown="ignore", so an unrecognised value degrades to the same
    # "unknown" that None produced before -- no worse than today, and better
    # whenever the caller knows.
    stage: str = Field(default="", max_length=40)

    # The deck's vintage, as a four-digit year, when the caller knows it.
    #
    # This is the temporal anchor claim verification needs: without it the
    # verifier reads a 2011 metric against 2026 evidence and reports the
    # difference as a refutation, which is how four true historical claims were
    # called lies at 0.96-0.97 confidence.
    #
    # Optional, and empty is honest: when it is absent the pipeline falls back
    # to inferring a year from the deck text, and when that finds nothing the
    # verifier is told the vintage is unknown rather than being given a guess.
    deck_date: str = Field(default="", max_length=4)

    @field_validator(
        "company_description", "filing_text", "extraction_method",
        "extraction_fallback_reason", "stage", "deck_date",
        mode="before",
    )
    @classmethod
    def treat_null_as_absent(cls, value):
        """An explicit null means the same thing as omitting the key.

        These fields are declared `str` with a default rather than
        `str | None`, so Pydantic accepted an absent key and rejected a null
        one. Found by posting a real deck to /analyze from a Python client:
        `"stage": null` -- the natural serialisation of "the extractor could
        not tell" -- came back 422 against a field documented as optional.
        """
        return "" if value is None else value

    @field_validator("claims", "founders", "deck_slides", mode="before")
    @classmethod
    def treat_null_list_as_empty(cls, value):
        """Same reasoning for the list fields, which have the same shape."""
        return [] if value is None else value

    @field_validator("deck_date")
    @classmethod
    def check_deck_year(cls, value: str) -> str:
        value = (value or "").strip()
        if value and not re.fullmatch(r"(19[89]\d|20[0-4]\d)", value):
            raise ValueError("deck_date must be a four-digit year between 1980 and 2049")
        return value

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
    # True when claim verification never ran (provider failure), as
    # opposed to running and finding nothing. The UI must not render
    # the second as the first.
    claims_verification_degraded: bool = False
    # Whether any component fell back because the language model was
    # unreachable, and which ones.
    #
    # `ventureflow_agent` has computed both since the degradation work, and
    # `db.py` persists them, but this response model never declared them --
    # so Pydantic dropped them on the way out and the frontend had no way to
    # tell a specialist that found nothing from one that never ran. That is
    # why an outage rendered as "No positive signals identified."
    provider_degraded: bool = False
    degraded_components: list[dict[str, Any]] = Field(default_factory=list)
    # Declared here on purpose. A field the pipeline sets but the response
    # model does not declare is dropped silently by Pydantic, which is how
    # `provider_degraded` reached the UI as False on reports whose every
    # component had failed.
    evidence_search_degraded: bool = False
    evidence_search_note: str = ""
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
    # Reject unknown fields. Same reasoning as DiligenceRequest: a misspelled
    # or renamed key that Pydantic silently ignores means the server acts on
    # something other than what the caller sent, with no error anywhere. A
    # 422 naming the bad field is strictly better than a confident wrong
    # result. The frontend sends only the fields declared here.
    model_config = ConfigDict(extra="forbid")

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
    # Per-slide text for the analysis request to echo back (see
    # DiligenceRequest.deck_slides), plus the coverage measurement itself so
    # the upload step can already say how much of the deck was understood.
    deck_slides: list[str] = Field(default_factory=list)
    extraction_coverage: dict = Field(default_factory=dict)
    extraction_fallback_reason: str = ""
    # Deck metadata the scoring model consumes.
    #
    # These were extracted and then silently discarded here: Pydantic drops any
    # key a response model does not declare, so `burn_rate` -- which the regex
    # extractor has always produced -- never reached the browser, and the UI
    # then hardcoded `burn_rate: null` on top of that. Two independent layers
    # of the same defect on one field.
    #
    # None means "the deck did not say", never a default. `deck_metadata`
    # abstains rather than guessing, so a null here is a real absence.
    burn_rate: float | None = None
    stage: str | None = None
    sector: str | None = None
    team_size: int | None = None
    github_url: str | None = None
    domain: str | None = None
    metadata_evidence: dict[str, str] = Field(default_factory=dict)
    # "PDF" / "PowerPoint" / "Word" / "plain text" / "Markdown". Surfaced so
    # the UI can say which reader ran rather than implying everything is a PDF.
    document_format: str = "PDF"
    # Where the analysed text actually came from. "text_layer" is text the
    # document contained; "ocr" was recognised from page images because there
    # was no text layer to read; "hybrid" is a thin text layer supplemented by
    # OCR of the slides.
    #
    # This is a first-class field rather than a footnote because OCR misreads
    # digits, and a diligence tool that presents a recognised revenue figure
    # identically to a read one is hiding the single thing a reader would want
    # to know about that number.
    text_source: str = "text_layer"
    ocr: dict = Field(default_factory=dict)
    # Whether this deck is in VentureFlow's tech-startup scope, decided here so
    # the user finds out at upload rather than after filling in the analysis
    # form. The binding decision is made again at /analyze -- see the comment
    # there for why this one cannot be the only check.
    scope_check: dict = Field(default_factory=dict)


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



# ── Accounts ────────────────────────────────────────────────────────────────


@app.post("/auth/register", response_model=AuthResponse, status_code=201)
async def register(request: RegisterRequest, http_request: Request):
    """Create an account and sign it in.

    Registration signs the user in directly rather than sending them to a login
    form: there is no email to verify (see auth.EMAIL_IS_UNVERIFIED_NOTE), so a
    second step would ask for the password they just chose and prove nothing.
    """
    try:
        email = auth.validate_email(request.email)
        password = auth.validate_password(request.password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    password_hash = await run_in_threadpool(auth.hash_password, password)
    try:
        user = await run_in_threadpool(
            create_user, email=email, password_hash=password_hash,
            display_name=request.display_name.strip(),
        )
    except UserAlreadyExists:
        # Deliberately explicit. Hiding this to avoid disclosing that an account
        # exists does not work on a registration form -- the attacker learns the
        # same fact from being unable to register -- and it strands a real user
        # who has simply forgotten they signed up.
        raise HTTPException(
            status_code=409,
            detail="An account with that email already exists. Sign in instead.",
        ) from None
    except Exception as exc:
        logger.exception("Registration failed")
        raise HTTPException(
            status_code=503, detail="Accounts are unavailable right now."
        ) from exc

    return await _issue_session(user, http_request)


@app.post("/auth/login", response_model=AuthResponse)
async def login(request: LoginRequest, http_request: Request):
    try:
        email = auth.normalise_email(request.email)
        row = await run_in_threadpool(get_user_by_email, email)
    except Exception as exc:
        logger.exception("Login lookup failed")
        raise HTTPException(
            status_code=503, detail="Accounts are unavailable right now."
        ) from exc

    if row is None:
        # Verify against a dummy hash so an unknown email costs the same time as
        # a wrong password. A fast rejection here tells an attacker which
        # addresses are registered.
        await run_in_threadpool(auth.waste_time_like_a_real_verification)
        raise HTTPException(status_code=401, detail="Wrong email or password.")

    ok = await run_in_threadpool(
        auth.verify_password, request.password, row["password_hash"]
    )
    if not ok:
        raise HTTPException(status_code=401, detail="Wrong email or password.")

    return await _issue_session(row, http_request)


async def _issue_session(user_row: dict, http_request: Request) -> AuthResponse:
    token, token_hash, expires = auth.new_session_token()
    await run_in_threadpool(
        create_session, token_hash=token_hash, user_id=str(user_row["id"]),
        expires_at=expires, user_agent=http_request.headers.get("user-agent", ""),
    )
    return AuthResponse(
        token=token,
        user=auth.public_user(user_row),
        expires_at=expires.isoformat(),
    )


@app.post("/auth/logout", status_code=204)
async def logout(request: Request):
    """Delete the presented session. Idempotent: logging out twice is fine, and
    logging out with no session is not an error."""
    token = _bearer_token(request)
    if token:
        try:
            await run_in_threadpool(delete_session, auth.hash_token(token))
        except Exception:
            logger.warning("Could not delete session on logout", exc_info=True)
    return Response(status_code=204)


@app.get("/auth/me")
async def whoami(request: Request):
    """Who is signed in, and whether accounts exist at all.

    `accounts_enabled` lets the frontend tell "you are signed out" from "this
    deployment has no database and cannot have accounts", which need different
    words on screen.
    """
    user = await current_user(request)
    try:
        total = await run_in_threadpool(count_users)
        enabled = True
    except Exception:
        logger.warning("Could not count users", exc_info=True)
        total, enabled = 0, False
    return {
        "user": auth.public_user(user),
        "accounts_enabled": enabled,
        "any_accounts_exist": total > 0,
        "email_verification_note": auth.EMAIL_IS_UNVERIFIED_NOTE,
        "password_min_length": auth.MIN_PASSWORD_LENGTH,
    }


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
    """Liveness, database reachability, AND configuration.

    Configuration is reported here because a CRITICAL log line is only seen by
    someone already reading logs, and the misconfiguration this guards against
    went unnoticed for an unknown period precisely because nobody was. An uptime
    check watching this endpoint sees `status: misconfigured` immediately.

    Deliberately does NOT return a 5xx for a config problem: the service is
    genuinely running and refusing traffic would turn a security gap into an
    outage. The payload carries the truth; the status code carries liveness.
    """
    config = current_config_report()
    try:
        database = "connected" if neon_healthcheck() else "unavailable"
        status = "healthy"
    except Exception:
        database, status = "unavailable", "degraded"

    if not config.ok:
        status = "misconfigured"
    return {
        "status": status,
        "database": database,
        "config": config.as_dict(),
    }


async def _perform_analysis(request: DiligenceRequest, on_stage=None,
                            owner_user_id: str | None = None):
    session_id = str(uuid.uuid4())
    similar_companies: list[dict[str, Any]] = []
    try:
        similar_companies = await run_in_threadpool(
            find_similar_companies, request.company_name, request.domain, request.sector
        )
    except Exception:
        logger.warning("Portfolio comparison unavailable", exc_info=True)
    # KEYWORD arguments, deliberately, and not positional ones.
    #
    # This call used to pass twelve positional arguments ending in `on_stage`.
    # `run_due_diligence`'s twelfth parameter is `deck_date`, not `on_stage`, so
    # every production analysis did two wrong things at once and reported
    # neither:
    #
    #   * `deck_date` received the stage CALLBACK -- a truthy function object --
    #     which flowed into `as_of=deck_date or _infer_deck_vintage(...)` and was
    #     formatted into the claim-verification prompt as "<function record_stage
    #     at 0x...>". The temporal grounding added to stop the verifier judging a
    #     2011 metric against 2026 evidence was therefore inert for every real
    #     user; it worked only in ml/scripts/run_real_deck_corpus.py, which
    #     passes deck_date by keyword, which is why the corpus results looked
    #     correct.
    #
    #   * `on_stage` fell back to None, so the pipeline never reported progress.
    #     The `stage` column added in migration 008 -- the whole point of which
    #     was letting a user tell a slow analysis from a hung one -- was never
    #     written outside tests, which stub _perform_analysis and so never
    #     exercised this line.
    #
    # Binding by keyword makes the parameter order unable to cause this again.
    report = await run_in_threadpool(
        functools.partial(
            run_due_diligence,
            company_name=request.company_name,
            company_description=request.company_description,
            claims_to_verify=request.claims,
            filing_text=request.filing_text,
            revenue=request.revenue,
            burn_rate=request.burn_rate,
            runway_months=request.runway_months,
            sector=request.sector,
            team_size=request.team_size,
            github_url=request.github_url,
            founders=request.founders,
            stage=request.stage,
            deck_date=request.deck_date,
            deck_slides=request.deck_slides,
            extraction_method=request.extraction_method,
            extraction_fallback_reason=request.extraction_fallback_reason,
            on_stage=on_stage,
        )
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
            owner_user_id=owner_user_id,
        )
    except Exception as exc:
        logger.exception("Failed to persist completed report")
        raise HTTPException(
            status_code=503,
            detail="Analysis completed but could not be saved. Please retry.",
        ) from exc
    # Derived analytics row. Deliberately after persist_report and deliberately
    # not wrapped in the same failure handling: the report is already safe on
    # disk at this point, and a projection of it must never be able to turn a
    # completed analysis into a 503 the user sees. record_analysed_company
    # swallows its own errors and returns None.
    await run_in_threadpool(
        record_analysed_company, report=report, report_id=report_id
    )

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
        claims_verification_degraded=bool(report.get("claims_verification_degraded")),
        provider_degraded=bool(report.get("provider_degraded")),
        degraded_components=report.get("degraded_components") or [],
        evidence_search_degraded=bool(report.get("evidence_search_degraded")),
        evidence_search_note=report.get("evidence_search_note") or "",
        report_id=report_id,
        session_id=session_id,
    )


def _merge_slide_text(layer_text: str, ocr_text: str) -> str:
    """One slide's text layer plus whatever OCR found that it did not already say.

    Naive concatenation would double-count: coverage is measured per line, and
    a line present in both halves would be counted twice, inflating the
    denominator and the `content_chars` figure the thin-deck caveat quotes.
    Comparing on letters and digits only absorbs the differences that do not
    matter -- OCR renders "$2 million/day" where the text layer has
    "$2 million / day" -- while keeping genuinely new lines.
    """
    if not ocr_text.strip():
        return layer_text
    if not layer_text.strip():
        return ocr_text

    def key(line: str) -> str:
        return re.sub(r"[^a-z0-9]", "", line.lower())

    seen = {key(line) for line in layer_text.splitlines() if key(line)}
    fresh = [
        line for line in ocr_text.splitlines()
        if key(line) and key(line) not in seen
    ]
    return layer_text if not fresh else layer_text + "\n" + "\n".join(fresh)


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
    # The company name is the subject of every web lookup this analysis will
    # make, and it arrives pre-filled from the uploaded filename. "02 uber.pdf"
    # reached founder research as the company "02 uber", which duly searched
    # for the founders of a company that does not exist and came back with
    # Delta Air Lines and Maximilien Robespierre among its sources.
    #
    # Cleaned here rather than only in the form, so a script or a direct API
    # call gets the same protection. See company_name.clean for why it declines
    # to touch anything that does not look like a filename.
    company_name_as_uploaded = company_name
    company_name = clean_company_name(company_name) or company_name
    if company_name != company_name_as_uploaded:
        logger.info("Company name cleaned for search: %r -> %r",
                    company_name_as_uploaded, company_name)

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

        # A scanned or image-exported deck is a valid, human-legible PDF whose
        # pages carry no text layer at all -- six well-known decks in this
        # project's own corpus are like this (Dropbox, LinkedIn, YouTube,
        # Facebook, WeWork, BuzzFeed), each extracting exactly 0 characters
        # across 20-40 pages.
        #
        # This used to be the end of the road: a 422 saying "VentureFlow has no
        # OCR". It now runs one, offline and free (see ocr_extractor.py), and
        # only refuses when OCR has also been tried and failed.
        #
        # OCR also runs on decks that DID extract text but very little of it per
        # page, because "has a text layer" and "has been read" are different
        # facts. Coinbase's real 2012 deck is 12 pages and 635 characters; its
        # content is in the images.
        layer = document.get("text_layer")
        stripped = (text or "").strip()
        text_source = "text_layer"
        ocr_result: dict[str, Any] = {}
        is_pdf = (document.get("format") or "").lower() == "pdf"

        needs_ocr = is_pdf and ocr_extractor.should_supplement(
            layer or "none", len(stripped), int(document.get("page_count") or 0)
        )
        if needs_ocr and ocr_extractor.is_available():
            ocr_result = await run_in_threadpool(ocr_extractor.ocr_pdf, file_bytes)
            if ocr_result.get("available"):
                ocr_text = ocr_result.get("text") or ""
                if not stripped:
                    text, text_source = ocr_text, "ocr"
                else:
                    # Both kept, each labelled. The text layer goes first
                    # because it is the more reliable of the two, and the
                    # boundary is explicit so nothing downstream has to guess
                    # which half a given sentence came from.
                    text = (
                        f"{text}\n\n"
                        f"--- The following was recognised from the page images "
                        f"(OCR), not read from the document's text layer ---\n\n"
                        f"{ocr_text}"
                    )
                    text_source = "hybrid"
                stripped = text.strip()
                logger.info(
                    "OCR supplied %d chars for %r (source=%s)",
                    ocr_result.get("chars", 0), company_name, text_source,
                )
            else:
                logger.warning(
                    "OCR did not produce text for %r: %s",
                    company_name, ocr_result.get("reason"),
                )

        if not stripped:
            # Say WHY, and say what was tried. "Could not extract readable text"
            # reads like a corrupt file and invites the user to retry the same
            # upload; naming the cause tells them what to do instead.
            tried = (
                f"OCR was also run and could not recognise any text "
                f"({ocr_result.get('reason', 'no reason given')}). "
                if ocr_result
                else (
                    f"OCR is not available on this server "
                    f"({ocr_extractor.unavailable_reason()}). "
                    if needs_ocr else ""
                )
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Nothing could be read from this file. "
                    f"{document['page_count']} page(s) were opened and text "
                    f"extraction found no usable content. {tried}"
                    f"Please re-export the deck as a text-based PDF, or paste "
                    f"its text directly."
                ),
            )
        if len(stripped) < 50:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Only {len(stripped)} characters of text could be read from this "
                    f"{document['format']} file across {document['page_count']} page(s) "
                    f"-- far too little to analyse. If the deck is mostly images, "
                    f"re-export it as a text-based PDF."
                ),
            )
        scope_check = await run_in_threadpool(tech_scope.classify, text, company_name)
        if not scope_check["in_scope"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "out_of_scope",
                    "message": (
                        f"This deck does not appear to describe a technology "
                        f"startup, so VentureFlow cannot analyse it."
                    ),
                    "scope_check": scope_check,
                },
            )

        info = await run_in_threadpool(extract_structured, text, company_name)

        # Measure how much of the deck actually reached a structured field,
        # here at the upload step, so "insufficient data" downstream can never
        # be confused with "we dropped it". PDFs give real slide boundaries;
        # other formats fall back to line-level coverage.
        slides: list[str] = []
        if is_pdf:
            try:
                slides = await run_in_threadpool(
                    pdf_extractor.extract_pages_from_pdf, file_bytes
                )
            except Exception:
                logger.warning("Per-page extraction failed", exc_info=True)
        # On an image-only deck the text layer yields empty pages, so coverage
        # would be measured against slides that are blank by construction --
        # reporting 0% understood for a deck OCR read perfectly well. Where a
        # page has no text layer, its OCR text is the slide.
        if ocr_result.get("available"):
            by_page = {
                page["page"]: page.get("text", "")
                for page in ocr_result.get("per_page") or []
            }
            if not any(s.strip() for s in slides):
                slides = [by_page.get(n, "") for n in sorted(by_page)]
            else:
                slides = [
                    _merge_slide_text(slide, by_page.get(index + 1, ""))
                    for index, slide in enumerate(slides)
                ]
        coverage = extraction_coverage.compute(text, info, slides or None)

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
            # Previously extracted and then dropped here, because Pydantic
            # discards any key the response model does not declare.
            burn_rate=info.get("burn_rate"),
            stage=info.get("stage"),
            sector=info.get("sector"),
            team_size=info.get("team_size"),
            github_url=info.get("github_url"),
            domain=info.get("domain"),
            metadata_evidence=info.get("metadata_evidence") or {},
            deck_slides=slides,
            extraction_coverage=coverage,
            extraction_fallback_reason=info.get("_fallback_reason", "") or "",
            scope_check=scope_check,
            text_source=text_source,
            # Only the summary travels, not `per_page` -- the per-page text is
            # already in `deck_slides` and would double the response size.
            ocr={
                key: ocr_result[key]
                for key in (
                    "pages_read", "pages_total", "chars", "truncated",
                    "truncation_note", "seconds", "engine", "provenance", "reason",
                )
                if key in ocr_result
            } if ocr_result else {},
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
    file: UploadFile = File(...),
    company_name: str = Form(default="Unknown Company", max_length=160),
):
    """Kept at its original path because the frontend and scripts/batch_deck_test.py
    both call it; it now accepts every format /upload-document does."""
    return await _extract_uploaded_document(file, company_name)


@app.post("/upload-document", response_model=PDFExtractResponse)
async def upload_document(
    file: UploadFile = File(...),
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
async def saved_reports(request: Request):
    """The caller's own reports, plus the ones nobody owns.

    This used to return every stored report to every caller over sequential
    integer ids -- for a product whose premise is confidential diligence on
    other people's companies, the most severe defect in the system. It is now
    scoped: a signed-in user sees their own work plus the pre-authentication
    rows, and an anonymous caller sees only the pre-authentication rows.
    """
    user = await current_user(request)
    try:
        return await run_in_threadpool(
            list_reports, 20, str(user["id"]) if user else None
        )
    except Exception as exc:
        logger.exception("Could not list saved reports")
        raise HTTPException(status_code=503, detail="Saved reports are currently unavailable.") from exc


@app.get("/reports/{report_id}", response_model=DiligenceResponse)
async def saved_report(report_id: str, request: Request):
    user = await current_user(request)
    try:
        stored = await run_in_threadpool(
            get_report, report_id, str(user["id"]) if user else None
        )
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
        claims_verification_degraded=bool(report.get("claims_verification_degraded")),
        provider_degraded=bool(report.get("provider_degraded")),
        degraded_components=report.get("degraded_components") or [],
        evidence_search_degraded=bool(report.get("evidence_search_degraded")),
        evidence_search_note=report.get("evidence_search_note") or "",
        report_id=report_id, session_id=stored_session,
    )


class DecisionRequest(BaseModel):
    # Reject unknown fields. Same reasoning as DiligenceRequest: a misspelled
    # or renamed key that Pydantic silently ignores means the server acts on
    # something other than what the caller sent, with no error anywhere. A
    # 422 naming the bad field is strictly better than a confident wrong
    # result. The frontend sends only the fields declared here.
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern="^(invest|pass)$")
    notes: str = Field(default="", max_length=2000)


async def _require_readable_report(report_id: str, http_request: Request) -> None:
    """404 unless the caller may read this report.

    One rule for every route that touches a report by id, so they cannot drift
    apart again: a report is reachable when it is unowned (shared, written
    before accounts existed) or when it belongs to the caller. That is exactly
    what GET /reports/{id} enforces.

    Four routes used to skip this entirely -- comments (read and write),
    decisions, and company history -- which let any caller read and write other
    users' private reports. 404 rather than 403 on purpose: a 403 confirms the
    id is real, and report ids are sequential integers.
    """
    user = await current_user(http_request)
    try:
        stored = await run_in_threadpool(
            get_report, report_id, str(user["id"]) if user else None
        )
    except Exception as exc:
        logger.exception("Could not load report %s for an ownership check", report_id)
        raise HTTPException(
            status_code=503, detail="Saved report is currently unavailable."
        ) from exc
    if not stored:
        raise HTTPException(status_code=404, detail="Saved report not found.")


@app.get("/companies/{company_name}/history")
async def company_score_history(company_name: str, request: Request):
    """Score history for one company, limited to reports the caller may see --
    powers Dashboard.tsx's score-trend chart once 2+ analyses exist."""
    user = await current_user(request)
    try:
        history = await run_in_threadpool(
            get_score_history, company_name,
            owner_user_id=str(user["id"]) if user else None,
        )
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
async def record_report_decision(
    report_id: str, request: DecisionRequest, http_request: Request
):
    """Record the user's own invest/pass call on a report. This is the
    feedback signal the firm-personalization ranking layer trains against
    (see ml/personalization.py) -- it accumulates from here, one decision
    at a time, and is worth nothing until there's real usage behind it.

    Ownership-checked: this table is TRAINING DATA, so an unchecked write here
    was not only an authorization gap but a way for any caller to poison the
    signal the personalization model learns from."""
    await _require_readable_report(report_id, http_request)
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


async def _render_report_export(
    report_id: str, fmt: str, request: Request | None = None
) -> Response:
    if fmt not in EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported export format. Supported: {', '.join(sorted(EXPORT_FORMATS))}",
        )
    try:
        # Scoped to the caller, exactly as GET /reports/{id} is.
        #
        # This used to call get_report(report_id) with no user at all, and the
        # bug that produced was the opposite of the obvious one. get_report
        # returns a row only when it is unowned OR owned by the id passed in,
        # so passing nothing did not leak private reports -- it hid them from
        # the person they belong to. A signed-in user could open their own
        # report (200) and got 404 from every download button on it.
        user = await current_user(request) if request is not None else None
        stored = await run_in_threadpool(
            get_report, report_id, str(user["id"]) if user else None
        )
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
async def saved_report_pdf(report_id: str, request: Request):
    """Kept at its original path -- the frontend links to it directly."""
    return await _render_report_export(report_id, "pdf", request)


@app.get("/reports/{report_id}/export/{fmt}")
async def saved_report_export(report_id: str, fmt: str, request: Request):
    """PDF, Word or Markdown, all from the same report content."""
    return await _render_report_export(report_id, fmt.lower(), request)


class CommentRequest(BaseModel):
    # Reject unknown fields. Same reasoning as DiligenceRequest: a misspelled
    # or renamed key that Pydantic silently ignores means the server acts on
    # something other than what the caller sent, with no error anywhere. A
    # 422 naming the bad field is strictly better than a confident wrong
    # result. The frontend sends only the fields declared here.
    model_config = ConfigDict(extra="forbid")

    author_name: str = Field(default="Anonymous", max_length=80)
    body: str = Field(min_length=1, max_length=4000)


@app.post("/reports/{report_id}/comments")
async def create_comment(
    report_id: str, request: CommentRequest, http_request: Request
):
    """Comment on a report the caller may read.

    `author_name` is still free text, not a verified identity -- accounts exist
    now, but comments are not yet attributed to them. What IS enforced is who
    can reach the report at all: this used to accept a comment on any report id
    from any caller, including other users' private analyses."""
    await _require_readable_report(report_id, http_request)
    try:
        comment = await run_in_threadpool(add_comment, report_id, request.author_name, request.body)
    except Exception as exc:
        logger.exception("Could not save comment for report %s", report_id)
        raise HTTPException(status_code=503, detail="Could not save this comment. Please retry.") from exc
    return comment


@app.get("/reports/{report_id}/comments")
async def get_comments(report_id: str, request: Request):
    # Ownership first. Comments on a private deal are as confidential as the
    # deal, and this used to return them to any caller who knew the id.
    await _require_readable_report(report_id, request)
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

    # The daily quota, in either of its shapes. The branch below only knew
    # Groq's own 429 wording ("tokens per day" / "TPD"); once that first 429
    # trips groq_client's breaker, later failures arrive as DailyQuotaExhausted,
    # whose message matches neither -- so they fell through to the raw
    # "Analysis failed: DailyQuotaExhausted: ..." instead of the message that
    # says when it resets and that retrying now is pointless.
    from groq_client import is_quota_exhausted
    if is_quota_exhausted(exc):
        return (
            "The Groq API daily token quota is exhausted, so the AI analysis "
            "steps could not run. This resets every 24 hours, or the tier can "
            "be upgraded at console.groq.com/settings/billing. Retrying now "
            "will fail the same way."
        )

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
    # Every log line emitted anywhere inside this analysis -- including from the
    # four specialist agents running concurrently -- carries this job id. That
    # is the specific thing that made past debugging sessions painful: four
    # agents interleaving output with no way to tell which run each belonged to.
    with observability.job_context(
        job_id=job_id, company=request_data.get("company_name"),
    ):
        await _run_analysis_job_inner(job_id, request_data)


async def _run_analysis_job_inner(job_id: str, request_data: dict[str, Any]) -> None:
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

        # Copy before popping: the caller's dict is also the row stored on the
        # job, and mutating it would strip the owner from a job that is later
        # reclaimed after a restart.
        payload = dict(request_data)
        owner_user_id = payload.pop(OWNER_KEY, None)
        report = await _perform_analysis(
            DiligenceRequest(**payload), on_stage=record_stage,
            owner_user_id=owner_user_id,
        )
        await run_in_threadpool(update_analysis_job, job_id, "complete", report.model_dump())
    except Exception as exc:
        logger.exception("Analysis job %s failed", job_id)
        observability.track_degradation(
            "analysis_job_failed", component="analysis_job",
            reason=f"{type(exc).__name__}: {exc}"[:200],
        )
        message = _describe_failure(exc)
        try:
            await run_in_threadpool(
                update_analysis_job, job_id, "failed", None, message,
            )
        except Exception:
            # If even recording the failure fails, the job would sit in
            # "running" forever and the frontend would poll indefinitely.
            logger.exception("Could not mark analysis job %s as failed", job_id)


# How many analyses may be in flight at once in this process.
#
# BackgroundTasks are unbounded by default: accept fifty decks and the process
# will try to run fifty analyses, each holding a thread, a Groq client and a
# few MB of extracted text. Render's free tier gives 512MB and one instance, so
# the realistic outcome is an OOM kill that takes every in-flight job with it --
# turning one overload into fifty orphaned jobs.
#
# Refusing work with a 429 the caller can retry is a better failure than
# accepting work that cannot be completed. Set low because the ceiling here is
# memory, not CPU, and because Groq's own per-minute token budget makes more
# than a handful of concurrent analyses pointless anyway.
MAX_CONCURRENT_ANALYSES = int(os.getenv("MAX_CONCURRENT_ANALYSES", "3"))


@app.post("/analyze", response_model=AnalysisJobResponse, status_code=202)
async def analyze_company(request: DiligenceRequest, background_tasks: BackgroundTasks,
                          http_request: Request):
    # Clean the company name here too.
    #
    # /upload-pdf is not the only way in: the frontend lets the name be edited
    # before submitting, and this endpoint is reachable directly. A name that
    # is still a filename here poisons claim verification, founder research and
    # the comparables search in exactly the way it did on Uber's deck.
    cleaned = clean_company_name(request.company_name)
    if cleaned and cleaned != request.company_name:
        logger.info("Company name cleaned for search: %r -> %r",
                    request.company_name, cleaned)
        request = request.model_copy(update={"company_name": cleaned})

    # VentureFlow analyses technology startups only.
    #
    # Enforced here rather than only at upload, because upload is not the only
    # way in: a caller can post a description straight to /analyze, and the
    # frontend lets a user edit the extracted text before submitting. A gate the
    # user can walk around by editing a field is not a gate.
    #
    # 422 with a structured `scope_check` body, so the UI can show the reason
    # and the evidence rather than a bare error string. See tech_scope.classify
    # for why this refuses only on positive evidence and abstains otherwise.
    scope_text = "\n".join(filter(None, [
        request.company_description, request.filing_text, " ".join(request.claims),
    ]))
    verdict = await run_in_threadpool(
        tech_scope.classify, scope_text, request.company_name
    )
    if not verdict["in_scope"]:
        logger.info("Refused out-of-scope analysis for %r: %s",
                    request.company_name, verdict["reason"])
        raise HTTPException(
            status_code=422,
            detail={
                "error": "out_of_scope",
                "message": (
                    f"{request.company_name} does not appear to be a technology "
                    f"startup, so VentureFlow cannot analyse it."
                ),
                "scope_check": verdict,
            },
        )

    # Shed load rather than accept work this process cannot finish.
    try:
        active = await run_in_threadpool(count_active_jobs)
    except Exception:
        # If the count is unavailable, accept the job. Failing an analysis
        # because a bookkeeping query failed would be a worse trade.
        logger.exception("Could not count active analysis jobs; accepting anyway")
        active = 0
    if active >= MAX_CONCURRENT_ANALYSES:
        raise HTTPException(
            status_code=429,
            detail=(
                f"{active} analyses are already running. This deployment runs at most "
                f"{MAX_CONCURRENT_ANALYSES} at once. Please retry in a few minutes."
            ),
        )

    # Whoever is signed in owns the resulting report. Anonymous analyses get a
    # NULL owner, which migration 010 defines as "visible to everyone" -- the
    # behaviour this deployment has always had.
    user = await current_user(http_request)
    payload = request.model_dump()
    payload[OWNER_KEY] = str(user["id"]) if user else None

    try:
        job_id = await run_in_threadpool(create_analysis_job, payload)
    except Exception as exc:
        logger.exception("Could not create analysis job")
        raise HTTPException(status_code=503, detail="Analysis queue is currently unavailable.") from exc
    background_tasks.add_task(_run_analysis_job, job_id, payload)
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

    # Reclaim on read, not only at startup.
    #
    # Startup reclamation handles a process that died and came back. It does not
    # handle the case where THIS process is alive but the job's worker thread is
    # not -- an OOM-killed thread, or a task that was never scheduled. The
    # frontend polls this endpoint every few seconds, so checking here is what
    # bounds how long a user can watch a dead job's spinner.
    if job["status"] in ("pending", "running"):
        try:
            reclaimed = await run_in_threadpool(reclaim_orphaned_jobs)
            if any(r["job_id"] == job_id for r in reclaimed):
                job = await run_in_threadpool(get_analysis_job, job_id)
        except Exception:
            logger.exception("Orphan reclamation during status poll failed")

    report = DiligenceResponse(**job["result"]) if job["status"] == "complete" and job.get("result") else None
    return AnalysisJobResponse(job_id=job["job_id"], status=job["status"], report=report, error=job.get("error_message"), stage=job.get("stage"))


@app.get("/observability")
async def observability_snapshot():
    """Aggregate degradation counts since this process started.

    Deliberately not a dashboard. The question worth answering is "how often is
    the analysis actually degraded in practice", and until now nothing anywhere
    could answer it -- every degradation was a log line nobody aggregated.
    """
    return observability.snapshot()


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
