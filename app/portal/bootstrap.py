"""Inisialisasi database + akun admin default dari .env."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.portal.db import Base, engine, session_scope
from app.portal.models import AuditLog, User
from app.portal.security import hash_password
from app.portal.settings import ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_USERNAME, DEFAULT_QUOTA_MB

log = logging.getLogger(__name__)


def init_db() -> None:
    Base.metadata.create_all(engine)


def seed_admin() -> None:
    """Buat admin dari .env hanya jika belum ada admin sama sekali."""
    with session_scope() as db:
        if db.scalar(select(User).where(User.role == "admin").limit(1)):
            return
        if not ADMIN_PASSWORD:
            log.warning("ADMIN_PASSWORD kosong di .env — admin default tidak dibuat.")
            return
        existing = db.scalar(select(User).where(User.username == ADMIN_USERNAME))
        if existing:
            existing.role = "admin"
            return
        db.add(User(
            username=ADMIN_USERNAME,
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            role="admin",
            must_change_password=True,
            quota_mb=DEFAULT_QUOTA_MB,
        ))
        db.add(AuditLog(username="system", action="admin.seed", target=ADMIN_USERNAME))
        log.info("Admin default '%s' dibuat dari .env", ADMIN_USERNAME)


def bootstrap() -> None:
    init_db()
    seed_admin()
