import time
from urllib.parse import parse_qs, urlencode, urlsplit

from cloud_auth import IDENTIFIER, signature
from metadata import parse_spotify_url
from remote_audio import GatewayError, GatewayHandler, backend_config, backend_request


class handler(GatewayHandler):
    def do_GET(self):
        query = parse_qs(urlsplit(self.path).query)
        job_id = query.get("job", [""])[0]
        if job_id and not IDENTIFIER.fullmatch(job_id):
            return self.reply(400, {"error": "Geçersiz indirme işi."})
        if "download" in query and not job_id:
            return self.reply(400, {"error": "Geçersiz indirme işi."})
        owner = self.session_owner()
        try:
            path = "/api/audio-jobs" + ("/" + job_id if job_id else "")
            status, data = backend_request(path, owner)
            if "download" not in query or status != 200:
                return self.reply(status, data)
            if data.get("state") != "done" or not data.get("download"):
                return self.reply(409, {"error": "Dosya henüz hazır değil veya indirme süresi doldu."})
            base, token = backend_config()
            expires = int(time.time()) + 300
            params = urlencode({"owner": owner, "expires": expires,
                                "signature": signature(token, job_id, owner, expires)})
            self.send_response(302)
            self.send_header("Location", f"{base}/api/audio-jobs/{job_id}/download?{params}")
            self.send_header("Content-Length", "0")
            self.common_headers()
            self.end_headers()
        except GatewayError as exc:
            return self.reply(exc.status, {"error": exc.message})

    def do_POST(self):
        if urlsplit(self.path).query:
            return self.reply(405, {"error": "Bu işlem desteklenmiyor."})
        # Browser requests must originate from this site. Non-browser clients have no Origin.
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return self.reply(403, {"error": "İstek bu siteden gelmeli."})
        try:
            payload = self.read_payload()
            _, _, canonical = parse_spotify_url(payload.get("url"))
            status, data = backend_request("/api/audio-jobs", self.session_owner(), {"url": canonical})
            return self.reply(status, data)
        except ValueError as exc:
            return self.reply(400, {"error": str(exc)})
        except GatewayError as exc:
            return self.reply(exc.status, {"error": exc.message})
