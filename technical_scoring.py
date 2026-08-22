"""Technical/GitHub scoring -- a rule-based repo-health rubric.

Deliberately NOT a trained model. `ml/README.md` explains why the trained
models in this project (Outcome Model, and the Claim/Risk models once
trained) are kept in `ml/`, separate from scoring like this: there is no
labeled "good repo" / "bad repo" dataset to train against, and inventing one
would mean encoding someone's opinion as if it were learned signal. A
transparent, individually-inspectable rubric is the honest tool for this job
-- every point awarded traces to one readable rule, not a black box.

Uses the public, unauthenticated GitHub REST API, which is adequate for the
request volume a due-diligence tool makes (60 requests/hour per IP). Set
GITHUB_TOKEN to raise that to 5,000/hour if this starts getting used heavily.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
_REPO_URL_RE = re.compile(
    r"github\.com[:/]+([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(?:\.git)?/?$"
)


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _parse_repo(github_url: str) -> tuple[str, str] | None:
    match = _REPO_URL_RE.search(github_url.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def score_repo(github_url: str, timeout: float = 8.0) -> dict[str, Any]:
    """Score a public GitHub repo 0-100 against a transparent rubric.

    Always returns a dict with `available`. On any failure (bad URL, private
    repo, API error, network unavailable) `available` is False with a
    human-readable `reason` -- this must never raise into the caller."""
    parsed = _parse_repo(github_url or "")
    if not parsed:
        return {"available": False, "reason": "Not a recognizable GitHub repo URL."}
    owner, repo = parsed

    try:
        repo_resp = requests.get(
            f"{GITHUB_API}/repos/{owner}/{repo}", headers=_headers(), timeout=timeout
        )
        if repo_resp.status_code == 404:
            return {"available": False, "reason": "Repository not found or private."}
        if repo_resp.status_code == 403:
            return {
                "available": False,
                "reason": "GitHub API rate limit hit. Set GITHUB_TOKEN to raise the limit.",
            }
        repo_resp.raise_for_status()
        repo_data = repo_resp.json()

        contributors_resp = requests.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/contributors",
            headers=_headers(),
            params={"per_page": 100, "anon": "true"},
            timeout=timeout,
        )
        contributors = contributors_resp.json() if contributors_resp.ok else []
        contributor_count = len(contributors) if isinstance(contributors, list) else 0

        commits_resp = requests.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/commits",
            headers=_headers(),
            params={"per_page": 100},
            timeout=timeout,
        )
        commits = commits_resp.json() if commits_resp.ok else []
        recent_commit_count = _count_recent_commits(commits, days=90) if isinstance(commits, list) else 0

        contents_resp = requests.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/contents",
            headers=_headers(),
            timeout=timeout,
        )
        file_names = (
            {item.get("name", "").lower() for item in contents_resp.json()}
            if contents_resp.ok and isinstance(contents_resp.json(), list)
            else set()
        )

        breakdown = _build_breakdown(
            repo_data=repo_data,
            contributor_count=contributor_count,
            recent_commit_count=recent_commit_count,
            file_names=file_names,
        )
        total = sum(item["points"] for item in breakdown)

        return {
            "available": True,
            "repo": f"{owner}/{repo}",
            "score": round(total),
            "breakdown": breakdown,
            "method": "rule_based_rubric",
            "caveat": (
                "A rubric over public repo metadata, not a trained model and not "
                "a code-quality review. Private repos, monorepos, and repos that "
                "intentionally squash-merge or mirror from elsewhere will score "
                "unfairly low on activity/contributor signals -- read the "
                "breakdown, don't take the total alone."
            ),
        }
    except requests.RequestException as exc:
        logger.warning("GitHub API unavailable for %s/%s: %s", owner, repo, exc)
        return {"available": False, "reason": f"GitHub API unavailable: {exc}"}
    except Exception as exc:  # noqa: BLE001 - this must never raise into the caller
        logger.exception("Unexpected error scoring repo %s/%s", owner, repo)
        return {"available": False, "reason": f"Unexpected error: {exc}"}


def _count_recent_commits(commits: list[dict], days: int) -> int:
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    count = 0
    for commit in commits:
        date_str = (
            commit.get("commit", {}).get("committer", {}).get("date")
            or commit.get("commit", {}).get("author", {}).get("date")
        )
        if not date_str:
            continue
        try:
            ts = datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if ts >= cutoff:
            count += 1
    return count


def _build_breakdown(
    *, repo_data: dict, contributor_count: int, recent_commit_count: int, file_names: set[str]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    # Recent activity -- up to 25 points
    activity_points = min(25, recent_commit_count * 2)
    items.append({
        "factor": "Recent activity (commits in last 90 days)",
        "points": activity_points, "max": 25,
        "reasoning": f"{recent_commit_count} commit(s) in the last 90 days.",
    })

    # Contributor count -- up to 20 points
    contributor_points = min(20, contributor_count * 4)
    items.append({
        "factor": "Contributor count",
        "points": contributor_points, "max": 20,
        "reasoning": f"{contributor_count} contributor(s) found (capped at 5 for full credit -- a single-founder repo isn't inherently bad, but a team with only one contributor after raising a round is worth asking about).",
    })

    # Tests / CI present -- up to 15 points
    has_tests = any(name in file_names for name in ("tests", "test", "__tests__", "spec"))
    has_ci = ".github" in file_names or any(
        name in file_names for name in (".circleci", ".travis.yml", "azure-pipelines.yml")
    )
    ci_points = (10 if has_tests else 0) + (5 if has_ci else 0)
    items.append({
        "factor": "Tests / CI configuration present",
        "points": ci_points, "max": 15,
        "reasoning": f"tests dir: {'found' if has_tests else 'not found'}; CI config: {'found' if has_ci else 'not found'} (checked top-level dir only).",
    })

    # README / LICENSE -- up to 10 points
    has_readme = any(name.startswith("readme") for name in file_names)
    has_license = any(name.startswith("license") for name in file_names) or bool(repo_data.get("license"))
    doc_points = (5 if has_readme else 0) + (5 if has_license else 0)
    items.append({
        "factor": "README and LICENSE present",
        "points": doc_points, "max": 10,
        "reasoning": f"README: {'found' if has_readme else 'missing'}; LICENSE: {'found' if has_license else 'missing'}.",
    })

    # Issue health -- up to 15 points
    open_issues = repo_data.get("open_issues_count", 0) or 0
    if open_issues == 0:
        issue_points = 15
        issue_reason = "No open issues (or issues disabled)."
    elif open_issues <= 10:
        issue_points = 10
        issue_reason = f"{open_issues} open issue(s) -- a healthy, actively-triaged range."
    elif open_issues <= 50:
        issue_points = 5
        issue_reason = f"{open_issues} open issues -- worth asking whether these are triaged."
    else:
        issue_points = 0
        issue_reason = f"{open_issues} open issues -- a large, possibly unmanaged backlog."
    items.append({
        "factor": "Issue backlog health", "points": issue_points, "max": 15, "reasoning": issue_reason,
    })

    # Repo maturity -- up to 15 points
    created_at = repo_data.get("created_at")
    age_days = 0
    if created_at:
        try:
            age_days = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            ).days
        except ValueError:
            age_days = 0
    age_points = min(15, round(age_days / 30))
    items.append({
        "factor": "Repo maturity (age)", "points": age_points, "max": 15,
        "reasoning": f"Repository is {age_days} day(s) old.",
    })

    return items
