from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from openpyxl import Workbook

from tools import build_bidder_review_matrix
from tools import evaluate_turnover_requirements
from tools import extract_tender_required_documents
from tools import run_phase1_identity_extraction


ROOT = Path(__file__).resolve().parents[1]
APP_DATA_ROOT = ROOT / "app_data" / "tenders"
DEFAULT_ENGINE = "paddle"

AGENT_STEPS = [
    ("agent_1_identity", "Agent 1: OCR, PAN/GSTIN, bidder identity"),
    ("agent_2_required_documents", "Agent 2: tender required documents"),
    ("agent_2_bidder_matrix", "Agent 2: bidder document matrix"),
    ("agent_3_turnover", "Agent 3: turnover evaluation"),
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return value.strip("._-") or "uploaded_file"


def make_run_id(label: str = "GeM_Tender") -> str:
    return f"{slugify(label)[:40]}_{time.strftime('%Y%m%d_%H%M%S')}"


def tender_root_for(run_id: str) -> Path:
    return APP_DATA_ROOT / slugify(run_id)


def status_path(tender_root: Path) -> Path:
    return tender_root / "pipeline_status.json"


def load_env_file(env_path: Path | None = None) -> None:
    env_path = env_path or ROOT / "tools" / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(env_path, override=False)
    except Exception:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

    if os.environ.get("GROQ_API_KEY"):
        os.environ.setdefault("TURNOVER_LLM_API_KEY", os.environ["GROQ_API_KEY"])
        os.environ.setdefault("TURNOVER_LLM_API_URL", evaluate_turnover_requirements.DEFAULT_GROQ_API_URL)
        os.environ.setdefault("TURNOVER_LLM_MODEL", evaluate_turnover_requirements.DEFAULT_GROQ_MODEL)


def write_status(tender_root: Path, payload: dict[str, Any]) -> None:
    tender_root.mkdir(parents=True, exist_ok=True)
    status_path(tender_root).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_status(tender_root: Path) -> dict[str, Any]:
    path = status_path(tender_root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def initial_status(tender_id: str, tender_root: Path) -> dict[str, Any]:
    return {
        "tender_id": tender_id,
        "tender_root": str(tender_root),
        "status": "queued",
        "started_at": "",
        "completed_at": "",
        "active_step": "",
        "steps": [
            {"step_id": step_id, "label": label, "status": "Pending", "started_at": "", "completed_at": "", "message": ""}
            for step_id, label in AGENT_STEPS
        ],
        "logs": [],
        "error": "",
    }


def append_log(status: dict[str, Any], message: str) -> None:
    status.setdefault("logs", []).append({"ts": now_iso(), "message": message})


def mark_step(status: dict[str, Any], step_id: str, step_status: str, message: str = "") -> None:
    status["active_step"] = step_id if step_status == "Running" else status.get("active_step", "")
    for step in status["steps"]:
        if step["step_id"] != step_id:
            continue
        step["status"] = step_status
        step["message"] = message
        if step_status == "Running":
            step["started_at"] = now_iso()
        if step_status in {"Completed", "Failed"}:
            step["completed_at"] = now_iso()
        return


def save_uploaded_file(destination_dir: Path, file_name: str, data: bytes) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    path = destination_dir / slugify(file_name)
    path.write_bytes(data)
    return path


def create_upload_workspace(
    run_id: str,
    tender_files: list[tuple[str, bytes]],
    bidder_files: dict[int, list[tuple[str, bytes]]],
    bidder_names: dict[int, str] | None = None,
    replace_existing: bool = False,
) -> Path:
    tender_root = tender_root_for(run_id)
    if tender_root.exists() and replace_existing:
        shutil.rmtree(tender_root)
    tender_dir = tender_root / "01_Tender_Documents"
    bidder_root = tender_root / "03_Bidder_Submissions"
    for file_name, data in tender_files:
        save_uploaded_file(tender_dir, file_name, data)
    for index, files in bidder_files.items():
        bidder_name = slugify((bidder_names or {}).get(index, "")) if bidder_names else ""
        folder_name = f"Bidder_{index:02d}" + (f"_{bidder_name}" if bidder_name else "")
        folder = bidder_root / folder_name
        for file_name, data in files:
            save_uploaded_file(folder, file_name, data)
    write_status(tender_root, initial_status(run_id, tender_root))
    return tender_root


def run_pipeline(
    tender_id: str,
    tender_root: str | Path,
    engine: str = DEFAULT_ENGINE,
    status_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    tender_root = Path(tender_root).resolve()
    status = read_status(tender_root) or initial_status(tender_id, tender_root)
    status["status"] = "running"
    status["started_at"] = status.get("started_at") or now_iso()
    append_log(status, "Pipeline started.")
    write_status(tender_root, status)

    def persist() -> None:
        write_status(tender_root, status)
        if status_callback:
            status_callback(status)

    try:
        load_env_file()

        mark_step(status, "agent_1_identity", "Running", "Extracting page text and bidder identity fields.")
        append_log(status, "Agent 1 started.")
        persist()
        identity_engine = DEFAULT_ENGINE if engine == "auto" else engine
        exit_code = run_phase1_identity_extraction.run(identity_engine, False, tender_id, tender_root)
        if exit_code:
            raise RuntimeError("Agent 1 finished with validation issues. See output logs.")
        mark_step(status, "agent_1_identity", "Completed", "Identity extraction completed.")
        append_log(status, "Agent 1 completed.")
        persist()

        mark_step(status, "agent_2_required_documents", "Running", "Extracting tender required-document attributes.")
        append_log(status, "Agent 2 requirement extraction started.")
        persist()
        exit_code = extract_tender_required_documents.run(tender_id, tender_root)
        if exit_code:
            raise RuntimeError("Agent 2 requirement extraction finished with validation issues.")
        mark_step(status, "agent_2_required_documents", "Completed", "Tender document attributes extracted.")
        append_log(status, "Agent 2 requirement extraction completed.")
        persist()

        mark_step(status, "agent_2_bidder_matrix", "Running", "Building bidder document review matrix.")
        append_log(status, "Agent 2 bidder matrix started.")
        persist()
        exit_code = build_bidder_review_matrix.run(tender_id, tender_root)
        if exit_code:
            raise RuntimeError("Agent 2 bidder matrix finished with validation issues.")
        mark_step(status, "agent_2_bidder_matrix", "Completed", "Bidder document matrix completed.")
        append_log(status, "Agent 2 bidder matrix completed.")
        persist()

        mark_step(status, "agent_3_turnover", "Running", "Evaluating turnover evidence.")
        append_log(status, "Agent 3 turnover evaluation started.")
        persist()
        exit_code = evaluate_turnover_requirements.run(tender_id, tender_root)
        if exit_code:
            raise RuntimeError("Agent 3 turnover evaluation finished with validation issues.")
        mark_step(status, "agent_3_turnover", "Completed", "Turnover evaluation completed.")
        append_log(status, "Agent 3 completed.")
        status["status"] = "completed"
        status["completed_at"] = now_iso()
        status["active_step"] = ""
        append_log(status, "Pipeline completed.")
        persist()
        return status
    except Exception as exc:
        status["status"] = "failed"
        status["error"] = str(exc)
        status["completed_at"] = now_iso()
        active_step = status.get("active_step")
        if active_step:
            mark_step(status, active_step, "Failed", str(exc))
        append_log(status, f"Pipeline failed: {exc}")
        persist()
        return status


def write_reviewed_workbook(path: Path, rows: list[dict[str, Any]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Reviewed Matrix"
    ws.append(headers)
    for row in rows:
        ws.append([row.get(header, "") for header in headers])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)
