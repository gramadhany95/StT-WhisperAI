"""Password hashing, session cookie bertanda, CSRF, rate limit login."""

from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.portal.settings import SECRET_KEY, SESSION_MAX_AGE

COOKIE_NAME = "stt_session"
MIN_PASSWORD_LEN = 8

_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="stt-session")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def generate_password() -> str:
    return secrets.token_urlsafe(9)


def validate_new_password(password: str, confirm: str) -> Optional[str]:
    if len(password) < MIN_PASSWORD_LEN:
        return f"Password minimal {MIN_PASSWORD_LEN} karakter."
    if password != confirm:
        return "Konfirmasi password tidak sama."
    return None


def make_session(user_id: int, session_version: int) -> str:
    return _serializer.dumps({"uid": user_id, "sv": session_version, "csrf": secrets.token_urlsafe(24)})


def read_session(cookie: Optional[str]) -> Optional[dict]:
    if not cookie:
        return None
    try:
        return _serializer.loads(cookie, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None


class LoginRateLimiter:
    """Batasi percobaan login gagal per IP (in-memory, per proses web)."""

    def __init__(self, max_failures: int = 10, window_sec: int = 300) -> None:
        self.max_failures = max_failures
        self.window_sec = window_sec
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, ip: str) -> deque[float]:
        q = self._fails[ip]
        cutoff = time.monotonic() - self.window_sec
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._prune(ip)) >= self.max_failures

    def fail(self, ip: str) -> None:
        with self._lock:
            self._prune(ip).append(time.monotonic())

    def reset(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)


login_limiter = LoginRateLimiter()
