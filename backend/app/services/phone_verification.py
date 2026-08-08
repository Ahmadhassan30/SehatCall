"""
DAWA phone-ownership verification.

Before DAWA will place scheduled calls to a number, a caregiver must prove that
the number is one they are entitled to have called. We prove it the same way the
product works: we ring the number and speak a short code, and the caregiver types
that code back. A number that cannot receive a voice call is useless to DAWA
anyway, so this checks exactly the capability the product depends on — which an
SMS would not.

Storage rules:
  - The plaintext code is NEVER stored. Only salt$sha256(salt + code).
  - The salt is per challenge, so no server-wide secret is required and the
    hashes stay valid across restarts and redeploys.
  - Codes expire, guesses are capped, and resends are rate-limited, so the
    6-digit space cannot be brute-forced and the number cannot be call-bombed.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

CODE_LENGTH = 6
CODE_TTL = timedelta(minutes=10)

# A 6-digit code has 1e6 possibilities. Capping guesses at 5 per issued code
# keeps the chance of a blind hit negligible; exhausting the cap forces a resend,
# which is itself rate-limited.
MAX_ATTEMPTS = 5

# Minimum gap between verification calls to the same patient. Without this,
# repeatedly hitting "resend" turns DAWA into a way to harass a phone number.
RESEND_COOLDOWN = timedelta(seconds=60)

# E.164: leading +, no leading zero on the country code, 8-15 digits total.
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class PhoneVerificationError(Exception):
    """Raised for any caller-correctable verification problem."""


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------

def normalise_phone(raw: str) -> str:
    """
    Return a clean E.164 number, or raise PhoneVerificationError.

    Accepts the spacing and punctuation people actually type (+92 300 1234567,
    +92-300-1234567) but refuses anything that is not unambiguously E.164.
    We deliberately do NOT guess a country code: inferring +92 for a local-format
    number would eventually dial the wrong person.
    """
    if not raw or not raw.strip():
        raise PhoneVerificationError("Phone number is required.")

    cleaned = re.sub(r"[\s\-()./]", "", raw.strip())

    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    if not cleaned.startswith("+"):
        raise PhoneVerificationError(
            "Include the country code, starting with '+' — for example +923001234567."
        )

    if not _E164_RE.match(cleaned):
        raise PhoneVerificationError(
            "That does not look like a valid phone number. "
            "Use the international format, for example +923001234567."
        )

    return cleaned


def mask_phone(phone: str) -> str:
    """Render a number for display/logs without exposing it in full."""
    if len(phone) <= 4:
        return "***"
    return f"{phone[:3]}{'*' * (len(phone) - 6)}{phone[-3:]}"


# ---------------------------------------------------------------------------
# Codes
# ---------------------------------------------------------------------------

def generate_code() -> str:
    """A cryptographically random zero-padded numeric code."""
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


def hash_code(code: str, salt: str | None = None) -> str:
    """
    Return "salt$digest". Salt is generated when not supplied.

    Self-contained by design: verifying only needs the stored string, so there is
    no server secret to rotate and no way for a config change to silently
    invalidate every live challenge.
    """
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}{code}".encode()).hexdigest()
    return f"{salt}${digest}"


def verify_code(code: str, stored: str) -> bool:
    """Constant-time comparison of a submitted code against "salt$digest"."""
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_code(code, salt), stored)


# ---------------------------------------------------------------------------
# Expiry helpers
# ---------------------------------------------------------------------------

def expiry_from(now: datetime) -> str:
    return (now + CODE_TTL).isoformat()


def is_expired(expires_at: str, now: datetime) -> bool:
    try:
        deadline = datetime.fromisoformat(expires_at)
    except ValueError:
        # An unparseable deadline is treated as expired: failing closed here
        # means corrupt data forces a resend rather than accepting a stale code.
        return True
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return now >= deadline


def cooldown_remaining(sent_at: str, now: datetime) -> int:
    """Seconds left before another verification call may be placed (0 if ready)."""
    try:
        sent = datetime.fromisoformat(sent_at)
    except ValueError:
        return 0
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    elapsed = now - sent
    if elapsed >= RESEND_COOLDOWN:
        return 0
    return int((RESEND_COOLDOWN - elapsed).total_seconds()) + 1


def spoken_code(code: str) -> str:
    """
    Space out the digits so the voice model reads them individually.

    Without this a realtime TTS model tends to read "472913" as a single large
    number, which is very hard to write down over a phone line.
    """
    return " ".join(code)
