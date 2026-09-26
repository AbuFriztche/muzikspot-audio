"""Local web server for Spotify metadata lookup."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import shutil
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, parse_qs, urlsplit
from urllib.request import urlopen

import audio_jobs
from cloud_auth import IDENTIFIER, TOKEN, valid_download
from metadata import lookup


ROOT = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    server_version = "MuzikBilgisi/2.0"

    def authorize_audio(self) -> bool:
        self.audio_owner = "local"
        secret = os.environ.get("AUDIO_BACKEND_TOKEN", "")
        if not secret:
            return True
        supplied = self.headers.get("Authorization", "").encode("utf-8")
        if hmac.compare_digest(supplied, ("Bearer " + secret).encode("utf-8")):
            owner = self.headers.get("X-Audio-Session", "")
            if IDENTIFIER.fullmatch(owner):
                self.audio_owner = owner
                return True
        parsed = urlsplit(self.path)
        match = re.fullmatch(r"/api/audio-jobs/([0-9a-f]{32})/download", parsed.path)
        query = parse_qs(parsed.query)
        owner = query.get("owner", [""])[0]
        if match and valid_download(secret, match[1], owner, query.get("expires", [""])[0], query.get("signature", [""])[0]):
            self.audio_owner = owner
            return True
        self.json_response(403, {"error": "İndirme erişimi doğrulanamadı."})
        return False

    def log_message(self, format_string: str, *args) -> None:
        if not self.path.startswith("/api/"):
            super().log_message(format_string, *args)

    def respond(self, status: int, body: bytes, mime: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: https://i.scdn.co https://*.spotifycdn.com; frame-src https://open.spotify.com; script-src 'self'; style-src 'self'; connect-src 'self' https://i.scdn.co https://*.spotifycdn.com; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, status: int, obj: dict) -> None:
        self.respond(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if self.path == "/readyz":
            return self.json_response(200 if audio_jobs.available() else 503, {"ok": audio_jobs.available()})
        if self.path.startswith("/api/") and not self.authorize_audio():
            return
        self.path = urlsplit(self.path).path
        if self.path == "/api/health":
            return self.json_response(200, {"ok": True, "app": "MuzikBilgisi/2.0", "audio_available": audio_jobs.available()})
        if self.path == "/api/audio-jobs":
            return self.json_response(200, {"jobs": audio_jobs.list_jobs(self.audio_owner)})
        job_match = re.fullmatch(r"/api/audio-jobs/([0-9a-f]{32})", self.path)
        if job_match:
            state = audio_jobs.snapshot(job_match[1], self.audio_owner)
            return self.json_response(200, state) if state else self.json_response(404, {"error": "İndirme işi bulunamadı."})
        file_match = re.fullmatch(r"/api/audio-jobs/([0-9a-f]{32})/download", self.path)
        if file_match:
            path = audio_jobs.download_path(file_match[1], self.audio_owner)
            if path is None:
                return self.json_response(404, {"error": "MP3 dosyası bulunamadı."})
            self.send_response(200)
            self.send_header("Content-Type", "application/zip" if path.suffix == ".zip" else "audio/mpeg")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(path.name)}")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            try:
                with path.open("rb") as source:
                    shutil.copyfileobj(source, self.wfile)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            audio_jobs.downloaded(file_match[1])
            return
        resources = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/particles.js": ("particles.js", "text/javascript; charset=utf-8"),
            "/id3.js": ("id3.js", "text/javascript; charset=utf-8"),
            "/zip.js": ("zip.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if self.path not in resources:
            return self.json_response(404, {"error": "Sayfa bulunamadı."})
        filename, mime = resources[self.path]
        return self.respond(200, (ROOT / filename).read_bytes(), mime)

    def do_POST(self) -> None:
        if not self.authorize_audio():
            return
        if self.path not in {"/api/lookup", "/api/audio-jobs"}:
            return self.json_response(404, {"error": "Sayfa bulunamadı."})
        origin = self.headers.get("Origin")
        allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        if origin and origin not in allowed:
            return self.json_response(403, {"error": "Bu istek yerel sayfadan gelmeli."})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.json_response(415, {"error": "JSON istek gerekli."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Geçersiz istek boyutu.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Geçersiz istek.")
            if self.path == "/api/lookup":
                return self.json_response(200, lookup(payload.get("url")))
            return self.json_response(202, audio_jobs.start(payload.get("url"), self.audio_owner))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self.json_response(400, {"error": str(exc)})
        except RuntimeError as exc:
            return self.json_response(503, {"error": str(exc)})
        except Exception:
            return self.json_response(502, {"error": "Spotify bilgileri şu anda alınamadı. Bağlantıyı kontrol edip yeniden deneyin."})


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    secret = os.environ.get("AUDIO_BACKEND_TOKEN", "")
    if (secret and not TOKEN.fullmatch(secret)) or (args.host not in {"127.0.0.1", "localhost", "::1"} and not secret):
        raise SystemExit("Dışa açık sunucu için AUDIO_BACKEND_TOKEN gerekli (32–128 URL-güvenli karakter).")
    address = f"http://{args.host}:{args.port}"
    try:
        server = LocalServer((args.host, args.port), Handler)
    except OSError as exc:
        try:
            with urlopen(f"{address}/api/health", timeout=2) as response:
                already_running = json.load(response).get("app") == "MuzikBilgisi/2.0"
        except Exception:
            already_running = False
        if already_running:
            print(f"Müzik Bilgisi zaten açık: {address}", flush=True)
            if not args.no_browser:
                webbrowser.open(address)
            return
        raise SystemExit(f"Yerel sunucu açılamadı ({address}): {exc}") from exc
    print(f"Müzik Bilgisi: {address}", flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
