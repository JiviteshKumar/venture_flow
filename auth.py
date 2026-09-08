"""Email and password accounts.

WHAT THIS IS FOR

The product had no user model. A single shared passphrase (`DEMO_ACCESS_TOKEN`)
established that a caller knew a secret, never who they were, so every report
lived in one globally readable pool -- `GET /reports` returned every uploaded
deck's analysis to anyone holding the passphrase. For a tool whose premise is
confidential diligence on other people's companies, that is the worst defect in
the system, and the shared passphrase was only ever a stopgap for it.

DESIGN NOTES, EACH OF WHICH IS A DELIBERATE CHOICE

**scrypt, from the standard library.** No bcrypt, argon2 or passlib is installed
and none is added. `hashlib.scrypt` is a memory-hard KDF in stdlib, which is the
property that matters against offline cracking; the parameters below are the
interactive-login set from the scrypt paper, tuned so a single hash costs ~100ms
on the machines this runs on. The encoded form carries its own parameters, so
raising them later does not invalidate existing hashes -- `verify_password`
reads whatever a stored hash was made with.

**Opaque session tokens, not JWTs.** A JWT cannot be revoked before expiry
without server-side state, which removes the only reason to prefer one. A row
per session can be deleted on logout and expired centrally. Only the SHA-256 of
the token is stored, so a database dump yields no usable session, for the same
reason password hashes are stored rather than passwords.

**Constant-time comparison everywhere**, and a dummy hash verification on
unknown emails, so the response time of a login does not reveal whether an
account exists.

**No email delivery.** Verification links, password resets and magic links all
need an SMTP provider or a transactional email service, and this project has
neither configured. Registering therefore creates a usable account immediately
and the email is an identifier rather than a verified address. That is stated
plainly at the point of registration rather than implied to be more than it is;
see `EMAIL_IS_UNVERIFIED_NOTE`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# scrypt parameters. n is the CPU/memory cost and dominates; r and p are the
# block size and parallelisation. n=2**14 with r=8 costs roughly 16MB and ~100ms
# per hash, which is a tolerable login latency and an expensive offline attack.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16

SESSION_TTL_DAYS = int(os.getenv("VENTUREFLOW_SESSION_TTL_DAYS", "30"))
TOKEN_BYTES = 32

# Deliberately permissive. Over-strict email regexes reject real addresses
# (plus-addressing, new TLDs, unicode domains) and buy nothing: the only test
# that proves an address works is sending to it, which this deployment cannot
# do. So this rejects what is obviously not an address and accepts the rest.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

MIN_PASSWORD_LENGTH = 10

EMAIL_IS_UNVERIFIED_NOTE = (
    "This deployment has no email provider configured, so addresses are not "
    "verified and there is no password-reset flow. Your email is an identifier, "
    "not a confirmed contact address."
)

# The most common passwords, checked because a length rule alone accepts
# "password12" and "1234567890". Not a substitute for a breach-corpus check --
# which would need a downloaded list this project does not ship -- and it does
# not pretend to be.
_OBVIOUS_PASSWORDS = {
    "password", "password1", "password12", "password123", "passw0rd123",
    "1234567890", "12345678910", "qwertyuiop", "letmein123", "iloveyou1",
    "admin12345", "welcome123", "abc123456789", "changeme123", "ventureflow",
}


class AuthError(Exception):
    """A failure the caller should surface to the user verbatim."""


def normalise_email(email: str) -> str:
    """Lower-cased and trimmed.

    The database has a UNIQUE constraint on `email`, so normalising here is what
    stops "Ada@Example.com" and "ada@example.com" becoming two accounts. Done in
    one place precisely because doing it in several is how they diverge.
    """
    return (email or "").strip().lower()


def validate_email(email: str) -> str:
    email = normalise_email(email)
    if not email:
        raise AuthError("Enter your email address.")
    if len(email) > 254:
        raise AuthError("That email address is too long.")
    if not _EMAIL_RE.match(email):
        raise AuthError("That does not look like an email address.")
    return email


def validate_password(password: str) -> str:
    """Length first, then obviousness.

    A minimum of 10 rather than the customary 8, and no composition rules. Forced
    symbol-and-digit rules push people towards `Password1!` and are worse than a
    length floor; NIST dropped them for that reason.
    """
    password = password or ""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(
            f"Use at least {MIN_PASSWORD_LENGTH} characters. Length matters more "
            f"than symbols — a short password with punctuation is easier to crack "
            f"than a long ordinary one."
        )
    if len(password) > 1024:
        # Unbounded input to a memory-hard KDF is a denial-of-service vector.
        raise AuthError("That password is too long (1024 characters maximum).")
    if password.lower() in _OBVIOUS_PASSWORDS:
        raise AuthError("That password is one of the most commonly used ones. Choose another.")
    return password


def hash_password(password: str) -> str:
    """Encode as `scrypt$n$r$p$salt$hash`, parameters included.

    Storing the parameters means today's hashes stay verifiable after the cost
    is raised, so the cost CAN be raised.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_N * _SCRYPT_R * 256,
    )
    return "$".join([
        "scrypt", str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    ])


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check against a stored hash. Never raises."""
    try:
        scheme, n, r, p, salt_b64, hash_b64 = (encoded or "").split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        n, r, p = int(n), int(r), int(p)
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
            dklen=len(expected), maxmem=n * r * 256,
        )
        return hmac.compare_digest(derived, expected)
    except Exception:
        # A malformed hash is a failed login, not a 500.
        logger.warning("Could not verify a stored password hash", exc_info=True)
        return False


# A real hash of a random password, verified against when the email is unknown,
# so that "no such account" and "wrong password" take the same time. Without it,
# a fast rejection tells an attacker the address is not registered.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def waste_time_like_a_real_verification() -> None:
    verify_password("not-the-password", _DUMMY_HASH)


def new_session_token() -> tuple[str, str, datetime]:
    """(token to give the client, hash to store, expiry).

    The token is generated here and never persisted; only its SHA-256 is.
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    return token, hash_token(token), expires


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def public_user(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """A user row with nothing secret in it.

    Exists so no endpoint can return `password_hash` by forgetting to strip it:
    the only shape that reaches a response is built here.
    """
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "display_name": row.get("display_name") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "email_verified": False,
        "email_verification_note": EMAIL_IS_UNVERIFIED_NOTE,
    }
