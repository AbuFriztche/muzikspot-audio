"""Vercel Python Function for the same lookup used by the local server."""

import json
from http.server import BaseHTTPRequestHandler

from metadata import lookup


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.reply(415, {"error": "JSON istek gerekli."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Geçersiz istek boyutu.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Geçersiz istek.")
            return self.reply(200, lookup(payload.get("url")))
        except ValueError as exc:
            return self.reply(400, {"error": str(exc)})
        except Exception:
            return self.reply(502, {"error": "Spotify bilgileri şu anda alınamadı. Bağlantıyı kontrol edip yeniden deneyin."})

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
