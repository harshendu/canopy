"""A tiny mock Jira server for the e2e connector flow — no real external calls.

Serves just the one endpoint canopy's Jira connector needs for a full sync
(`POST /rest/api/3/search/jql`), returning a fixed set of issues. The connector's
`config.base_url` is pointed here, so the *real* connector code path runs end-to-end
against a mocked interface. Runs on a background thread; stop() shuts it down.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Two issues: an epic (-> summary task) and a story parented under it.
ISSUES = [
    {
        "id": "10001", "key": "MOCK-1",
        "fields": {"summary": "Checkout epic", "status": {"name": "In Progress"},
                   "issuetype": {"name": "Epic"}, "updated": "2026-05-01T10:00:00.000+0000"},
    },
    {
        "id": "10002", "key": "MOCK-2",
        "fields": {"summary": "Build cart", "status": {"name": "To Do"},
                   "issuetype": {"name": "Story"}, "updated": "2026-05-02T10:00:00.000+0000",
                   "parent": {"id": "10001"}},
    },
]


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/rest/api/3/search/jql"):
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)  # drain the JQL body; we always return the same set
            payload = {"issues": ISSUES, "isLast": True, "nextPageToken": None}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args: object) -> None:  # silence per-request logging
        pass


class MockJira:
    def __init__(self) -> None:
        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> "MockJira":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
