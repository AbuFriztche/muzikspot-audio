"""Exercise real HTTP gateway/worker isolation and large-file redirects locally."""

import http.client
import json
import os
import threading
import time
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

import app
import audio_jobs
from api.audio import handler as AudioHandler
from api.health import handler as HealthHandler
from cloud_auth import signature
from remote_audio import GatewayError, backend_config


TOKEN = "a" * 48


class GatewayRouter(AudioHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/api/health":
            return HealthHandler.do_GET(self)
        parts = urlsplit(self.path).path.split("/")
        if parts[1:3] == ["api", "audio-jobs"]:
            params = {"job": parts[3]} if len(parts) > 3 else {}
            if len(parts) > 4:
                params["download"] = "1"
            self.path = "/api/audio" + ("?" + urlencode(params) if params else "")
        return super().do_GET()


def call(port, path, *, headers=None, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("POST" if body is not None else "GET", path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"AUDIO_BACKEND_TOKEN": TOKEN, "VERCEL": ""})
        self.environment.start()
        self.temp = Path(__file__).resolve().parent / ("cloud_test_" + uuid.uuid4().hex)
        self.temp.mkdir()
        self.downloads = patch.object(audio_jobs, "DOWNLOADS", self.temp)
        self.jobs = patch.dict(audio_jobs.JOBS, {}, clear=True)
        self.downloads.start()
        self.jobs.start()
        self.worker = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        os.environ["AUDIO_BACKEND_URL"] = f"http://127.0.0.1:{self.worker.server_port}"
        self.gateway = ThreadingHTTPServer(("127.0.0.1", 0), GatewayRouter)
        for server in (self.worker, self.gateway):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def tearDown(self):
        for server in (self.gateway, self.worker):
            server.shutdown()
            server.server_close()
        self.jobs.stop()
        self.downloads.stop()
        if self.temp.resolve().parent == Path(__file__).resolve().parent and self.temp.name.startswith("cloud_test_"):
            for directory in self.temp.iterdir():
                for path in directory.iterdir():
                    path.unlink()
                directory.rmdir()
            self.temp.rmdir()
        self.environment.stop()

    def make_job(self, owner):
        job_id = uuid.uuid4().hex
        directory = audio_jobs.DOWNLOADS / job_id
        directory.mkdir()
        # Bigger than a typical function body limit; only the worker streams it.
        content = b"ID3" + b"x" * (5 * 1024 * 1024)
        (directory / "probe.mp3").write_bytes(content)
        audio_jobs.JOBS[job_id] = {"id": job_id, "owner": owner, "state": "done", "title": "Probe",
                                  "kind": "track", "filename": "probe.mp3", "message": "Ready"}
        return job_id, directory, content

    def test_ready_file_redirects_and_streams_without_exposing_other_sessions(self):
        with patch.object(audio_jobs, "available", return_value=True):
            code, headers, body = call(self.gateway.server_port, "/api/health")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["audio_available"])
        self.assertEqual(json.loads(body)["audio_state"], "ready")
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        owner = cookie.split("=", 1)[1]
        job_id, directory, content = self.make_job(owner)
        code, _, body = call(self.gateway.server_port, "/api/audio-jobs")
        self.assertEqual(json.loads(body)["jobs"], [])
        code, _, _ = call(self.gateway.server_port, f"/api/audio-jobs/{job_id}")
        self.assertEqual(code, 404)
        code, _, body = call(self.gateway.server_port, "/api/audio-jobs", headers={"Cookie": cookie})
        self.assertEqual(json.loads(body)["jobs"][0]["id"], job_id)
        code, headers, body = call(self.gateway.server_port, f"/api/audio-jobs/{job_id}/download", headers={"Cookie": cookie})
        self.assertEqual(code, 302)
        self.assertEqual(body, b"")
        self.assertNotIn(TOKEN, headers["Location"])
        location = urlsplit(headers["Location"])
        code, _, _ = call(self.worker.server_port, location.path)
        self.assertEqual(code, 403)
        completed = threading.Event()
        original_downloaded = audio_jobs.downloaded
        def finish(job):
            original_downloaded(job)
            completed.set()
        with patch.object(audio_jobs, "downloaded", side_effect=finish):
            code, headers, downloaded = call(self.worker.server_port, location.path + "?" + location.query)
            self.assertTrue(completed.wait(2))
        self.assertEqual(code, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(downloaded, content)
        self.assertFalse(directory.exists())
        self.assertEqual(audio_jobs.snapshot(job_id)["state"], "downloaded")

    def test_expired_and_tampered_download_links_cannot_read_files(self):
        owner = uuid.uuid4().hex
        job_id, directory, _ = self.make_job(owner)
        for deadline, supplied in [(int(time.time()) - 1, None), (int(time.time()) + 300, "0" * 64)]:
            params = urlencode({"owner": owner, "expires": deadline,
                                "signature": supplied or signature(TOKEN, job_id, owner, deadline)})
            code, _, _ = call(self.worker.server_port, f"/api/audio-jobs/{job_id}/download?{params}")
            self.assertEqual(code, 403)
            self.assertTrue(directory.exists())

    def test_missing_backend_keeps_metadata_mode_available(self):
        with patch.dict(os.environ, {"AUDIO_BACKEND_URL": "", "AUDIO_BACKEND_TOKEN": ""}):
            code, _, body = call(self.gateway.server_port, "/api/health")
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["audio_available"])
        self.assertEqual(json.loads(body)["audio_state"], "unconfigured")

    def test_sleeping_backend_reports_retryable_state(self):
        with patch("api.health.backend_request", side_effect=GatewayError(502, "Bağlanılamadı.")):
            code, _, body = call(self.gateway.server_port, "/api/health")
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["audio_available"])
        self.assertEqual(json.loads(body)["audio_state"], "offline")

    def test_start_normalizes_spotify_link_and_passes_owner(self):
        owner = uuid.uuid4().hex
        headers = {"Cookie": "audio_session=" + owner, "Content-Type": "application/json"}
        link = "https://open.spotify.com/intl-tr/album/4GHjuL2otqfI3tRLk7v5XF?si=example"
        with patch.object(audio_jobs, "start", return_value={"id": uuid.uuid4().hex, "state": "queued"}) as start:
            code, _, _ = call(self.gateway.server_port, "/api/audio", headers=headers, body=json.dumps({"url": link}))
            self.assertEqual(code, 202)
            start.assert_called_once_with("https://open.spotify.com/album/4GHjuL2otqfI3tRLk7v5XF", owner)
            code, _, _ = call(self.gateway.server_port, "/api/audio", headers=headers, body=json.dumps({"url": "https://example.com/file"}))
            self.assertEqual(code, 400)
            self.assertEqual(start.call_count, 1)

    def test_vercel_requires_https_and_worker_rejects_wrong_secret(self):
        with patch.dict(os.environ, {"VERCEL": "1"}):
            with self.assertRaises(GatewayError):
                backend_config()
        code, _, _ = call(self.worker.server_port, "/api/audio-jobs", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()
