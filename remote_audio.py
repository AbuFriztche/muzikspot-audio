"""Small JSON gateway; audio bytes go straight from the worker to the browser."""

import json
import os
import uuid
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cloud_auth import IDENTIFIER, TOKEN


class GatewayError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def backend_config() -> tuple[str, str]:
    base = os.environ.get("AUDIO_BACKEND_URL", "").strip().rstrip("/")
    token = os.environ.get("AUDIO_BACKEND_TOKEN", "").strip()
    parsed = urlparse(base)
    local = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"} and not os.getenv("VERCEL")
    if (not parsed.hostname or (parsed.scheme != "https" and not local)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not TOKEN.fullmatch(token)):
        raise GatewayError(503, "İndirme hizmeti henüz bağlanmadı. Şarkı bilgilerini inceleyebilirsin.")
    return base, token


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never send the private worker token to a redirected host.
        return None


def backend_request(path: str, owner: str, payload: dict | None = None) -> tuple[int, dict]:
    base, token = backend_config()
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(base + path, data=body, headers={
        "Authorization": "Bearer " + token,
        "X-Audio-Session": owner,
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with build_opener(NoRedirect()).open(request, timeout=8) as response:
            data = json.loads(response.read(1024 * 1024))
            if not isinstance(data, dict):
                raise ValueError("Invalid response")
            return response.status, data
    except HTTPError as exc:
        if exc.code in {400, 404, 429, 503}:
            try:
                data = json.loads(exc.read(4096))
                if isinstance(data, dict) and isinstance(data.get("error"), str):
                    return exc.code, {"error": data["error"]}
            except (ValueError, UnicodeDecodeError):
                pass
        raise GatewayError(502, "İndirme hizmeti isteği tamamlayamadı. Biraz sonra yeniden dene.") from exc
    except (URLError, OSError, ValueError):
        raise GatewayError(502, "İndirme hizmetine bağlanılamadı. Biraz sonra yeniden dene.")


class GatewayHandler(BaseHTTPRequestHandler):
    def session_owner(self) -> str:
        if hasattr(self, "_session_owner"):
            return self._session_owner
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            pass
        value = cookie.get("audio_session")
        candidate = value.value if value else ""
        self._new_session = not bool(IDENTIFIER.fullmatch(candidate))
        self._session_owner = uuid.uuid4().hex if self._new_session else candidate
        return self._session_owner

    def common_headers(self) -> None:
        owner = self.session_owner()
        if self._new_session:
            secure = "; Secure" if os.getenv("VERCEL") or self.headers.get("X-Forwarded-Proto") == "https" else ""
            self.send_header("Set-Cookie", f"audio_session={owner}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800{secure}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def reply(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.common_headers()
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self) -> dict:
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise GatewayError(415, "JSON istek gerekli.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError()
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except (ValueError, UnicodeDecodeError):
            raise GatewayError(400, "Geçersiz istek.")
