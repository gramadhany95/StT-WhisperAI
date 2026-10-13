"""Client FRI Mini CDN (API v1): token JWT, upload, unduh, hapus."""

from __future__ import annotations

import io
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Iterator, Optional

import httpx

from app.portal.settings import CDN_API_KEY, CDN_API_SECRET, CDN_BASE_URL, CDN_ENABLED

_SCOPES = ["files:upload", "files:download", "files:list", "files:delete"]
_TIMEOUT = httpx.Timeout(30.0, read=600.0, write=600.0)


class CdnError(RuntimeError):
    pass


class CdnRejected(CdnError):
    """CDN menolak file (mis. MIME tidak diizinkan / terlalu besar)."""

    def __init__(self, message: str, allowed_mimes: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.allowed_mimes = allowed_mimes or []


class CdnClient:
    def __init__(self) -> None:
        self.api = f"{CDN_BASE_URL}/api/v1"
        self._token: Optional[str] = None
        self._token_exp = 0.0
        self._lock = threading.Lock()

    # ---------- auth ----------
    def _get_token(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._token and time.time() < self._token_exp - 300:
                return self._token
            r = httpx.post(
                f"{self.api}/auth/token",
                json={"api_secret": CDN_API_SECRET, "subject": "stt-portal", "scopes": _SCOPES},
                headers={"X-API-Key": CDN_API_KEY, "Accept": "application/json"},
                timeout=30,
            )
            if r.status_code != 200:
                raise CdnError(f"Auth CDN gagal ({r.status_code}): {r.text[:200]}")
            data = r.json()
            self._token = data["access_token"]
            self._token_exp = time.time() + int(data.get("expires_in", 3600))
            return self._token

    def _headers(self, force: bool = False) -> dict[str, str]:
        return {
            "X-API-Key": CDN_API_KEY,
            "Authorization": f"Bearer {self._get_token(force)}",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Request dengan re-auth sekali saat 401 dan retry saat 429/5xx."""
        reauth = False
        for attempt in range(5):
            body = kwargs.get("files")
            if body:
                for _, (_, fh, _) in body.items():
                    if hasattr(fh, "seek"):
                        fh.seek(0)
            r = httpx.request(method, f"{self.api}{path}", headers=self._headers(reauth), timeout=_TIMEOUT, **kwargs)
            if r.status_code == 401 and not reauth:
                reauth = True
                continue
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("Retry-After") or 2 ** attempt)
                time.sleep(min(wait, 30))
                continue
            return r
        return r

    # ---------- operasi ----------
    def ping(self) -> bool:
        self._get_token(force=True)
        return True

    def _upload(self, fh: IO[bytes], filename: str, mime: str, metadata: Optional[dict]) -> int:
        r = self._request(
            "POST",
            "/upload",
            files={"file": (filename, fh, mime)},
            data={"metadata": json.dumps(metadata or {})},
        )
        if r.status_code == 201:
            return int(r.json()["data"]["id"])
        if r.status_code in (413, 422):
            try:
                d = r.json()
            except ValueError:
                d = {"message": r.text[:200]}
            raise CdnRejected(d.get("message", "File ditolak CDN"), d.get("allowed_mimes"))
        raise CdnError(f"Upload CDN gagal ({r.status_code}): {r.text[:200]}")

    def upload(self, path: Path, filename: str, mime: str, metadata: Optional[dict] = None) -> int:
        with open(path, "rb") as fh:
            return self._upload(fh, filename, mime, metadata)

    def upload_bytes(self, data: bytes, filename: str, mime: str, metadata: Optional[dict] = None) -> int:
        return self._upload(io.BytesIO(data), filename, mime, metadata)

    @contextmanager
    def stream(self, file_id: int) -> Iterator[httpx.Response]:
        reauth = False
        for _ in range(2):
            with httpx.stream("GET", f"{self.api}/download/{file_id}", headers=self._headers(reauth), timeout=_TIMEOUT) as r:
                if r.status_code == 401 and not reauth:
                    reauth = True
                    continue
                if r.status_code != 200:
                    r.read()
                    raise CdnError(f"Unduh CDN gagal ({r.status_code}): {r.text[:200]}")
                yield r
                return
        raise CdnError("Unduh CDN gagal (auth)")

    def download_to(self, file_id: int, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.stream(file_id) as r, open(dest, "wb") as out:
            for chunk in r.iter_bytes(1024 * 1024):
                out.write(chunk)

    def delete(self, file_id: int) -> None:
        r = self._request("DELETE", f"/files/{file_id}")
        if r.status_code not in (200, 404):
            raise CdnError(f"Hapus CDN gagal ({r.status_code}): {r.text[:200]}")


cdn: Optional[CdnClient] = CdnClient() if CDN_ENABLED else None
