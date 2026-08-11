"""CLI for the PAN / GSTIN / MCA registry verification layer.

Usage (from the repo root):

    python -m tools.verification.run_verification --tender-root app_data/tenders/<run_id>
    python -m tools.verification.run_verification --tender-root <root> --services pan,gstin
    python -m tools.verification.run_verification --tender-root <root> --bidder-id Bidder_01 ^
        --cin Bidder_01=U12345MH2010PTC123456

Providers default to the in-process mock. Set VERIFY_<SVC>_PROVIDER=http and
VERIFY_<SVC>_BASE_URL in tools/.env to go through HTTP (the local mock server,
or — once VERIFY_ENABLED=true and credentials exist — the real registries).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python tools/verification/run_verification.py` as well as -m form.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.verification.engine import run_verification  # noqa: E402
from tools.verification.schema import ALL_SERVICES  # noqa: E402


def load_env() -> None:
    try:
        from tools.pipeline_runner import load_env_file

        load_env_file()
    except Exception:
        # The runner may be mid-edit or its heavy imports unavailable;
        # fall back to whatever is already in the environment.
        pass


def parse_cin_args(values: list[str]) -> dict[str, str]:
    cin_map: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"--cin expects BIDDER_ID=CIN, got: {item}")
        bidder_id, cin = item.split("=", 1)
        cin_map[bidder_id.strip()] = cin.strip().upper()
    return cin_map


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PAN/GSTIN/MCA registry verification.")
    parser.add_argument("--tender-root", required=True, help="Tender workspace root (run folder).")
    parser.add_argument("--bidder-id", action="append", default=[], help="Limit to bidder id (repeatable).")
    parser.add_argument(
        "--services",
        default=",".join(ALL_SERVICES),
        help=f"Comma-separated subset of: {', '.join(ALL_SERVICES)}",
    )
    parser.add_argument(
        "--cin",
        action="append",
        default=[],
        metavar="BIDDER_ID=CIN",
        help="Manual CIN/LLPIN for a bidder (repeatable); overrides document extraction.",
    )
    args = parser.parse_args()

    tender_root = Path(args.tender_root).resolve()
    if not tender_root.exists():
        print(f"Tender root does not exist: {tender_root}")
        return 2

    load_env()
    services = tuple(part.strip().casefold() for part in args.services.split(",") if part.strip())
    unknown = [service for service in services if service not in ALL_SERVICES]
    if unknown:
        print(f"Unknown service(s): {', '.join(unknown)}. Valid: {', '.join(ALL_SERVICES)}")
        return 2

    summary = run_verification(
        tender_root,
        bidder_ids=args.bidder_id or None,
        services=services,
        cin_map=parse_cin_args(args.cin),
        triggered_by="cli",
    )
    if summary.get("error"):
        return 1
    print(f"Summary: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
