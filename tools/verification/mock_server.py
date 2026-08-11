"""Local mock registry server (stdlib only) for PAN / GSTIN / MCA lookups.

Serves the same fixture data as the in-process ``MockProvider`` but over real
HTTP, so the ``HttpProvider`` path (URLs, auth headers, timeouts, HTTP errors)
is rehearsed before real registry credentials exist.

Run from the repo root:

    python -m tools.verification.mock_server

Routes:
    GET /pan/{PAN}
    GET /gstin/{GSTIN}
    GET /mca/cin/{CIN}
    GET /mca/search?name=<company name>

Behavior switches:
    - If VERIFY_PAN_API_KEY / VERIFY_GSTIN_API_KEY / VERIFY_MCA_API_KEY is set,
      the matching route requires the same value in the ``x-api-key`` header
      (401 otherwise) so authentication wiring can be tested.
    - Append ``?simulate=500|429|timeout`` to any route to test failure paths.

Point the client at it via tools/.env:
    VERIFY_PAN_PROVIDER=http
    VERIFY_PAN_BASE_URL=http://127.0.0.1:8877/pan
    (similarly /gstin and /mca/cin; MCA search uses {base}/search)
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.verification import fixtures

DEFAULT_PORT = 8877


def _expected_key(service: str) -> str:
    return os.environ.get(f"VERIFY_{service.upper()}_API_KEY", "")


class MockRegistryHandler(BaseHTTPRequestHandler):
    server_version = "MockRegistry/1.0"

    def do_GET(self) -> None:  # noqa: N802 - http.server naming convention
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        simulate = (query.get("simulate", [""])[0] or "").casefold()
        parts = [part for part in parsed.path.split("/") if part]

        service, status, body = self._route(parts, query)

        if service and not self._authorized(service):
            self._send(401, {"error_code": "UNAUTHORIZED", "message": "Missing or wrong x-api-key."})
            return
        if simulate == "timeout":
            time.sleep(float(os.environ.get("VERIFY_MOCK_TIMEOUT_SLEEP", "35")))
        elif simulate == "500":
            status, body = 500, {"error_code": "INTERNAL_ERROR", "message": "Simulated failure."}
        elif simulate == "429":
            status, body = 429, {"error_code": "RATE_LIMITED", "message": "Simulated throttle."}
        self._send(status, body)

    def _route(self, parts: list[str], query: dict[str, list[str]]):
        if len(parts) == 2 and parts[0] == "pan":
            return "pan", *fixtures.pan_response(urllib.parse.unquote(parts[1]))
        if len(parts) == 2 and parts[0] == "gstin":
            return "gstin", *fixtures.gstin_response(urllib.parse.unquote(parts[1]))
        if len(parts) == 3 and parts[0] == "mca" and parts[1] == "cin":
            return "mca", *fixtures.mca_cin_response(urllib.parse.unquote(parts[2]))
        if len(parts) == 2 and parts[0] == "mca" and parts[1] == "search":
            name = (query.get("name", [""])[0] or "").strip()
            return "mca", *fixtures.mca_search_response(name)
        return "", 404, {"error_code": "UNKNOWN_ROUTE", "path": "/".join(parts)}

    def _authorized(self, service: str) -> bool:
        expected = _expected_key(service)
        if not expected:
            return True
        return self.headers.get("x-api-key", "") == expected

    def _send(self, status: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[mock-registry] {self.address_string()} {fmt % args}")


def main() -> None:
    port = int(os.environ.get("VERIFY_MOCK_SERVER_PORT", DEFAULT_PORT))
    server = ThreadingHTTPServer(("127.0.0.1", port), MockRegistryHandler)
    print(f"Mock registry server listening on http://127.0.0.1:{port}")
    print("Routes: /pan/{PAN}  /gstin/{GSTIN}  /mca/cin/{CIN}  /mca/search?name=...")
    print("Stop with Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
