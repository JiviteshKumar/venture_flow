"""Refuse to run silently misconfigured.

WHY

`ALLOWED_ORIGIN_REGEX` and `DEMO_ACCESS_TOKEN` have been unset on Render for an
unknown period -- long enough that nobody can say when it started. The
consequences were not subtle: the frontend actually in use was CORS-blocked, and
`curl https://.../reports` returned every stored report, for every company
anyone had uploaded, to any anonymous caller.

Both failures were *silent*. The server logged healthy 200s for responses the
browser then discarded, and the ungated database looked exactly like a working
one. There was a `logger.warning` for the second case, which is precisely the
problem: a warning in a stream nobody aggregates is indistinguishable from
nothing at all.

WHAT THIS DOES

Declares what production actually requires, checks it at startup, and makes the
result impossible to miss in three places at once:

  * a CRITICAL log line naming each missing variable and what breaks without it;
  * `/health` reports `config: misconfigured` and lists the problems, so an
    uptime check sees it rather than a human having to read logs;
  * optionally refuses to boot at all, when STRICT_CONFIG is set.

Refusing to boot is NOT the default. On a single-instance free tier that turns a
security gap into a total outage, and the person who can fix it may be asleep.
The honest default is to run, serve, and shout. `STRICT_CONFIG=true` is there
for anyone who would rather fail closed, which is the right choice once there is
more than one instance.

WHAT COUNTS AS PRODUCTION

Inferred rather than declared, because a deployment that forgets to set
`ENVIRONMENT=production` is exactly the deployment that forgets the rest. Any
non-localhost allowed origin, or a configured origin regex, means a real
frontend is pointed at this process.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ConfigProblem:
    variable: str
    severity: str          # "critical" | "warning"
    consequence: str       # what is broken right now, in user-visible terms
    example: str = ""


@dataclass
class ConfigReport:
    looks_deployed: bool
    problems: list[ConfigProblem] = field(default_factory=list)

    @property
    def critical(self) -> list[ConfigProblem]:
        return [p for p in self.problems if p.severity == "critical"]

    @property
    def ok(self) -> bool:
        return not self.critical

    def as_dict(self) -> dict:
        return {
            "status": "ok" if self.ok else "misconfigured",
            "looks_deployed": self.looks_deployed,
            "problems": [
                {"variable": p.variable, "severity": p.severity,
                 "consequence": p.consequence, "example": p.example}
                for p in self.problems
            ],
        }


def _is_local(origin: str) -> bool:
    return origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1")


def check_configuration(
    *,
    origins: list[str],
    allowed_origin_regex: str | None,
    demo_access_token: str | None,
    requires_signin: bool = False,
) -> ConfigReport:
    """Inspect the environment and report what is missing.

    Pure: takes the values rather than reading globals, so it is testable
    without reimporting the application.
    """
    looks_deployed = any(not _is_local(o) for o in origins) or bool(allowed_origin_regex)
    report = ConfigReport(looks_deployed=looks_deployed)

    # Required everywhere -- the app cannot do its job without these.
    if not (os.getenv("GROQ_API_KEY") or "").strip():
        report.problems.append(ConfigProblem(
            variable="GROQ_API_KEY",
            severity="critical",
            consequence=(
                "Every LLM-backed component fails. Note the specific way it "
                "fails: an empty key produces an empty 'Authorization: Bearer ' "
                "header, httpx rejects it, and the SDK re-raises that as "
                "APIConnectionError -- so a missing key is reported as "
                "'provider unreachable' rather than as a missing key."
            ),
            example="gsk_...",
        ))

    if not (os.getenv("DATABASE_URL") or os.getenv("NEON_DATABASE_URL") or "").strip():
        report.problems.append(ConfigProblem(
            variable="DATABASE_URL",
            severity="critical",
            consequence="No report can be persisted or retrieved; every analysis is lost.",
            example="postgresql://user:password@host/dbname?sslmode=require",
        ))

    if not looks_deployed:
        return report

    # Required only once a real frontend points at this process -- and only
    # while the passphrase is the ONLY thing standing in front of the data.
    #
    # This rule was written when the deployed API had no accounts, so an unset
    # passphrase really did mean every report was readable over sequential
    # integer ids. Production mode changed that: VENTUREFLOW_ENV=production
    # makes every non-public route answer 401 to a caller without a session,
    # and reports are scoped to the account that created them. Still reporting
    # CRITICAL "THE API IS OPEN" there is not a small inaccuracy -- /health
    # returns `status: misconfigured` for a correctly locked deployment, which
    # is how a real warning stops being read.
    if not demo_access_token and not requires_signin:
        report.problems.append(ConfigProblem(
            variable="DEMO_ACCESS_TOKEN",
            severity="critical",
            consequence=(
                "THE API IS OPEN. Every stored report -- company names, scores, "
                "full memos for other people's confidential decks -- is readable "
                "by any anonymous caller, over sequential integer ids that make "
                "the table trivially enumerable."
            ),
            example="a long random passphrase",
        ))

    if not allowed_origin_regex:
        report.problems.append(ConfigProblem(
            variable="ALLOWED_ORIGIN_REGEX",
            severity="warning",
            consequence=(
                "Any Vercel deployment whose hostname is not in ALLOWED_ORIGINS "
                "is CORS-blocked. The symptom is deceptive: the server logs a "
                "healthy 200 and the browser discards the response, so the "
                "frontend shows a bare 'Network Error'."
            ),
            example=r"^https://venture-flow-[a-z0-9-]+\.vercel\.app$",
        ))

    if not (os.getenv("TRUST_PROXY_HEADERS") or "").strip():
        report.problems.append(ConfigProblem(
            variable="TRUST_PROXY_HEADERS",
            severity="warning",
            consequence=(
                "Behind Render's load balancer every visitor shares one rate-limit "
                "bucket, because request.client.host is the proxy rather than the "
                "user. The limiter then trips far sooner than intended."
            ),
            example="true",
        ))

    return report


def enforce(report: ConfigReport) -> None:
    """Log the report at a severity nobody can miss, and optionally refuse to boot."""
    if report.ok and not report.problems:
        logger.info("Configuration check passed (deployed=%s)", report.looks_deployed)
        return

    for problem in report.problems:
        line = (
            "CONFIG %s: %s is not set. %s"
            % (problem.severity.upper(), problem.variable, problem.consequence)
        )
        if problem.example:
            line += f" Expected value looks like: {problem.example}"
        if problem.severity == "critical":
            logger.critical(line)
        else:
            logger.warning(line)

    if report.critical:
        missing = ", ".join(p.variable for p in report.critical)
        logger.critical(
            "STARTING ANYWAY WITH %d CRITICAL CONFIGURATION PROBLEM(S): %s. "
            "/health will report status=misconfigured until they are fixed. "
            "Set STRICT_CONFIG=true to make this refuse to start instead.",
            len(report.critical), missing,
        )
        if (os.getenv("STRICT_CONFIG") or "").strip().lower() in {"1", "true", "yes"}:
            raise RuntimeError(
                f"Refusing to start: missing required configuration ({missing}). "
                f"STRICT_CONFIG is set."
            )
