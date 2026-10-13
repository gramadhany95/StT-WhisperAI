"""Pengaturan runtime yang disimpan di tabel settings."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.portal.models import Setting


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def get_flag(db: Session, key: str) -> bool:
    return get_setting(db, key) == "1"


def set_flag(db: Session, key: str, value: bool) -> None:
    set_setting(db, key, "1" if value else "0")


def get_float(db: Session, key: str) -> Optional[float]:
    try:
        return float(get_setting(db, key))
    except ValueError:
        return None
