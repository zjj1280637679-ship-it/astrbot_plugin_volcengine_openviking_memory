"""In-process mock of the hosted OpenViking Context HTTP API for tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


class MockOVHandler(BaseHTTPRequestHandler):
    sessions: dict = {}
    messages: dict = {}
    committed: dict = {}
    fail_search_context = False

    def log_message(self, *args):
        pass

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _auth_ok(self) -> bool:
        return (self.headers.get("Authorization") or "").startswith("Bearer test-key")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {"status": "ok"})
        if path.startswith("/api/v1/sessions/"):
            if not self._auth_ok():
                return self._send(401, {"status": "error", "error": {"code": "AuthenticationError"}})
            sid = path.rsplit("/", 1)[-1].split("?")[0]
            if sid in self.sessions or "auto_create=true" in self.path:
                self.sessions.setdefault(sid, True)
                return self._send(200, {"status": "ok", "result": {"session_id": sid, "uri": f"viking://user/test/sessions/{sid}"}})
            return self._send(404, {"status": "error", "error": {"code": "NotFound"}})
        return self._send(404, {"status": "error"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/v1/sessions":
            if not self._auth_ok():
                return self._send(401, {"status": "error", "error": {"code": "AuthenticationError"}})
            sid = (self._body().get("session_id") or f"sess-{len(self.sessions)}")
            self.sessions[sid] = True
            self.messages[sid] = []
            return self._send(200, {"status": "ok", "result": {"session_id": sid}})
        if path.startswith("/api/v1/sessions/") and path.endswith("/messages"):
            if not self._auth_ok():
                return self._send(401, {"status": "error", "error": {"code": "AuthenticationError"}})
            sid = path.split("/")[4]
            if sid not in self.sessions:
                return self._send(404, {"status": "error", "error": {"code": "NotFound"}})
            self.messages.setdefault(sid, []).append(self._body())
            return self._send(200, {"status": "ok", "result": {"accepted": True}})
        if path.startswith("/api/v1/sessions/") and path.endswith("/commit"):
            if not self._auth_ok():
                return self._send(401, {"status": "error", "error": {"code": "AuthenticationError"}})
            sid = path.split("/")[4]
            self.committed[sid] = self.committed.get(sid, 0) + 1
            return self._send(200, {"status": "ok", "result": {"session_id": sid, "status": "accepted"}})
        if path == "/api/v1/search/find":
            if not self._auth_ok():
                return self._send(401, {"status": "error", "error": {"code": "AuthenticationError"}})
            body = self._body()
            q = body.get("query", "")
            return self._send(200, {
                "status": "ok",
                "result": {
                    "memories": [
                        {
                            "uri": f"viking://user/test/memories/preferences/coffee_{q}.md",
                            "context_type": "memory",
                            "level": 2,
                            "score": 0.9 if "咖啡" in q or "coffee" in q.lower() else 0.4,
                            "category": "preferences",
                            "abstract": "用户喜欢喝冰美式咖啡。",
                            "overview": "",
                        },
                        {
                            "uri": "viking://user/test/memories/entities/name.md",
                            "context_type": "memory",
                            "level": 2,
                            "score": 0.3,
                            "category": "entities",
                            "abstract": "用户名叫小测。",
                            "overview": "",
                        },
                    ],
                    "resources": [],
                    "skills": [],
                    "total": 2,
                },
            })
        if path == "/api/v1/search/search":
            if MockOVHandler.fail_search_context:
                return self._send(400, {"status": "error", "error": {"code": "InvalidArgument"}})
            body = self._body()
            return self._send(200, {
                "status": "ok",
                "result": {
                    "entries": [
                        {"uri": "viking://user/test/memories/preferences/x.md", "category": "preferences",
                         "score": 0.8, "detail": "abstract", "text": "用户喜欢喝冰美式咖啡。", "origin": "self"}
                    ],
                    "rendered": "<memory>用户喜欢喝冰美式咖啡。</memory>",
                },
            })
        return self._send(404, {"status": "error"})


class MockOVServer:
    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockOVHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def reset(self):
        MockOVHandler.sessions.clear()
        MockOVHandler.messages.clear()
        MockOVHandler.committed.clear()
