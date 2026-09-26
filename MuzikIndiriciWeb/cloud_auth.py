"""Shared authentication for the Vercel gateway and the audio worker."""

import hashlib
import hmac
import re
import time


IDENTIFIER = re.compile(r"^[0-9a-f]{32}$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def signature(secret: str, job_id: str, owner: str, expires: int) -> str:
    value = f"download\n{job_id}\n{owner}\n{expires}".encode()
    return hmac.new(secret.encode(), value, hashlib.sha256).hexdigest()


def valid_download(secret: str, job_id: str, owner: str, expires: str, supplied: str) -> bool:
    if not TOKEN.fullmatch(secret) or not IDENTIFIER.fullmatch(job_id) or not IDENTIFIER.fullmatch(owner):
        return False
    try:
        deadline = int(expires)
    except (TypeError, ValueError):
        return False
    if not time.time() <= deadline <= time.time() + 600:
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", supplied):
        return False
    return hmac.compare_digest(signature(secret, job_id, owner, deadline), supplied)
