from remote_audio import GatewayError, GatewayHandler, backend_request


class handler(GatewayHandler):
    def do_GET(self):
        try:
            status, data = backend_request("/api/health", self.session_owner())
            available = status == 200 and data.get("audio_available") is True
            return self.reply(200, {"ok": True, "audio_available": available,
                                    "audio_state": "ready" if available else "offline",
                                    "message": "İndirme hazır." if available else "İndirme hizmeti şu anda kullanılamıyor."})
        except GatewayError as exc:
            return self.reply(200, {"ok": True, "audio_available": False,
                                    "audio_state": "unconfigured" if exc.status == 503 else "offline",
                                    "message": exc.message})
