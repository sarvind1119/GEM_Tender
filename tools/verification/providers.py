"""Verification providers and response adapters.

Two transports behind one interface:

- ``MockProvider`` — in-process, answers from ``fixtures.py``. Always allowed.
- ``HttpProvider`` — stdlib ``urllib.request`` against a configured base URL.
  Intended first for the local mock server (``mock_server.py``) and later for
  the real PAN / GSTN / MCA services: the swap is env configuration plus, if
  the real shapes differ, the one request-builder / parse function per service.

Egress guard: ``HttpProvider`` refuses to call a non-localhost URL unless
``VERIFY_ENABLED=true`` — external verification is an explicit, gated event.

The ``parse_*_response`` adapters normalize provider-shaped payloads into
``VerificationResult`` records and are the entire real-API swap surface.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from tools.verification import fixtures
from tools.verification.schema import (
    NAME_MATCH_NOT_TESTED,
    OUTCOME_ERROR,
    OUTCOME_NOT_FOUND,
    OUTCOME_SKIPPED,
    OUTCOME_STATUS_FLAG,
    OUTCOME_VERIFIED,
    SERVICE_GSTIN,
    SERVICE_MCA,
    SERVICE_PAN,
    VerificationResult,
    name_match,
    review_note_for,
)

DEFAULT_TIMEOUT_SECONDS = 20
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

# (http_status, body) tuple; status 0 means the request never completed.
RawResponse = tuple[int, dict[str, Any]]


class VerificationProvider(Protocol):
    name: str

    def verify_pan(self, pan: str, bidder_name_hint: str = "") -> RawResponse: ...

    def verify_gstin(self, gstin: str, bidder_name_hint: str = "") -> RawResponse: ...

    def verify_cin(self, cin: str, bidder_name_hint: str = "") -> RawResponse: ...

    def search_company(self, company_name: str) -> RawResponse: ...


class MockProvider:
    """In-process provider answering directly from fixtures."""

    name = "mock"

    def verify_pan(self, pan: str, bidder_name_hint: str = "") -> RawResponse:
        return fixtures.pan_response(pan, bidder_name_hint)

    def verify_gstin(self, gstin: str, bidder_name_hint: str = "") -> RawResponse:
        return fixtures.gstin_response(gstin, bidder_name_hint)

    def verify_cin(self, cin: str, bidder_name_hint: str = "") -> RawResponse:
        return fixtures.mca_cin_response(cin, bidder_name_hint)

    def search_company(self, company_name: str) -> RawResponse:
        return fixtures.mca_search_response(company_name)


class HttpProvider:
    """Generic HTTP provider for one service (pan | gstin | mca).

    URL layout (mock server and, by default, real providers):
      GET {base_url}/{value}                  for pan/gstin/cin lookups
      GET {base_url}/search?name={query}      for MCA name search
    If a real provider needs a different request shape (POST body, signed
    headers), adjust ``_request`` for that service here — nothing else changes.
    """

    def __init__(self, service: str) -> None:
        self.service = service
        env = service.upper()
        self.base_url = (os.environ.get(f"VERIFY_{env}_BASE_URL") or "").rstrip("/")
        self.api_key = os.environ.get(f"VERIFY_{env}_API_KEY", "")
        self.name = os.environ.get(f"VERIFY_{env}_PROVIDER_NAME", f"http:{service}")
        try:
            self.timeout = float(os.environ.get("VERIFY_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
        except ValueError:
            self.timeout = DEFAULT_TIMEOUT_SECONDS

    def _egress_check(self) -> str:
        if not self.base_url:
            return f"VERIFY_{self.service.upper()}_BASE_URL is not configured."
        host = urllib.parse.urlsplit(self.base_url).hostname or ""
        if host not in LOCAL_HOSTS and os.environ.get("VERIFY_ENABLED", "").casefold() != "true":
            return (
                f"External verification is disabled (VERIFY_ENABLED is not 'true'); "
                f"call to {host} was not made."
            )
        return ""

    def _request(self, url: str) -> RawResponse:
        blocked = self._egress_check()
        if blocked:
            return 0, {"_egress_blocked": blocked}
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            status = exc.code
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return 0, {"_transport_error": str(exc)}
        try:
            return status, json.loads(body)
        except json.JSONDecodeError:
            return status, {"_transport_error": f"Non-JSON response (HTTP {status})."}

    def _lookup(self, value: str) -> RawResponse:
        return self._request(f"{self.base_url}/{urllib.parse.quote(value.strip().upper())}")

    def verify_pan(self, pan: str, bidder_name_hint: str = "") -> RawResponse:
        return self._lookup(pan)

    def verify_gstin(self, gstin: str, bidder_name_hint: str = "") -> RawResponse:
        return self._lookup(gstin)

    def verify_cin(self, cin: str, bidder_name_hint: str = "") -> RawResponse:
        return self._lookup(cin)

    def search_company(self, company_name: str) -> RawResponse:
        query = urllib.parse.urlencode({"name": company_name.strip()})
        return self._request(f"{self.base_url}/search?{query}")


def get_provider(service: str) -> VerificationProvider:
    mode = os.environ.get(f"VERIFY_{service.upper()}_PROVIDER", "mock").casefold()
    if mode == "http":
        return HttpProvider(service)
    return MockProvider()


# --------------------------------------------------------------------------
# Response adapters: provider-shaped raw JSON -> normalized VerificationResult
# --------------------------------------------------------------------------


def _base_result(
    service: str,
    raw: RawResponse,
    provider: str,
    *,
    bidder_id: str,
    bidder_name: str,
    input_value: str,
) -> VerificationResult:
    status_code, body = raw
    result = VerificationResult(
        service=service,
        input_value=input_value,
        bidder_id=bidder_id,
        bidder_name=bidder_name,
        outcome=OUTCOME_ERROR,
        provider=provider,
        verified_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        raw_response_sha256=hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    )
    result.provider_ref = f"{provider}-{result.raw_response_sha256[:12]}"
    if "_egress_blocked" in body:
        result.outcome = OUTCOME_SKIPPED
        result.extra = {"detail": body["_egress_blocked"]}
    elif "_transport_error" in body:
        result.extra = {"detail": body["_transport_error"]}
    elif status_code == 404 or body.get("error_code") == "RECORD_NOT_FOUND":
        result.outcome = OUTCOME_NOT_FOUND
    elif status_code != 200:
        result.extra = {
            "detail": f"HTTP {status_code}: {body.get('error_code') or body.get('message', '')}"
        }
    else:
        # Leave outcome for the service-specific parser to refine.
        result.outcome = OUTCOME_VERIFIED
    return result


def _apply_name_match(result: VerificationResult) -> None:
    if result.registered_name:
        result.name_match_score, result.name_match_band = name_match(
            result.bidder_name, result.registered_name
        )
    else:
        result.name_match_score, result.name_match_band = 0.0, NAME_MATCH_NOT_TESTED


def _finalize(result: VerificationResult) -> VerificationResult:
    _apply_name_match(result)
    result.review_note = review_note_for(result)
    return result


def parse_pan_response(
    raw: RawResponse, provider: str, *, bidder_id: str, bidder_name: str, input_value: str
) -> VerificationResult:
    result = _base_result(
        SERVICE_PAN, raw, provider,
        bidder_id=bidder_id, bidder_name=bidder_name, input_value=input_value,
    )
    _status_code, body = raw
    if result.outcome == OUTCOME_VERIFIED:
        pan_status = str(body.get("pan_status", ""))
        result.registered_name = str(body.get("name_on_card", ""))
        result.extra = {"last_updated": body.get("last_updated", "")}
        if pan_status == "E":
            result.registry_status = "Valid"
        else:
            result.registry_status = f"Registry flag '{pan_status}'"
            result.outcome = OUTCOME_STATUS_FLAG
    return _finalize(result)


def parse_gstin_response(
    raw: RawResponse, provider: str, *, bidder_id: str, bidder_name: str, input_value: str
) -> VerificationResult:
    result = _base_result(
        SERVICE_GSTIN, raw, provider,
        bidder_id=bidder_id, bidder_name=bidder_name, input_value=input_value,
    )
    _status_code, body = raw
    if result.outcome == OUTCOME_VERIFIED:
        status = str(body.get("sts", ""))
        result.registry_status = status or "Unknown"
        result.registered_name = str(body.get("lgnm", ""))
        result.trade_name = str(body.get("tradeNam", ""))
        result.extra = {
            "registration_date": body.get("rgdt", ""),
            "state_jurisdiction": body.get("stjCd", ""),
        }
        if status.casefold() != "active":
            result.outcome = OUTCOME_STATUS_FLAG
    return _finalize(result)


def parse_mca_response(
    raw: RawResponse, provider: str, *, bidder_id: str, bidder_name: str, input_value: str
) -> VerificationResult:
    result = _base_result(
        SERVICE_MCA, raw, provider,
        bidder_id=bidder_id, bidder_name=bidder_name, input_value=input_value,
    )
    _status_code, body = raw
    if result.outcome == OUTCOME_VERIFIED:
        status = str(body.get("companyStatus", ""))
        result.registry_status = status or "Unknown"
        result.registered_name = str(body.get("companyName", ""))
        result.extra = {
            "roc": body.get("rocName", ""),
            "incorporation_date": body.get("dateOfIncorporation", ""),
        }
        if status.casefold() != "active":
            result.outcome = OUTCOME_STATUS_FLAG
    return _finalize(result)


PARSERS = {
    SERVICE_PAN: parse_pan_response,
    SERVICE_GSTIN: parse_gstin_response,
    SERVICE_MCA: parse_mca_response,
}
