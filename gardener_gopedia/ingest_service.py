"""Orchestrate Gopedia ingest (sync/async) and update IngestRun rows."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from gardener_gopedia.core.config import get_settings
from gardener_gopedia.gopedia_client import GopediaClient
from gardener_gopedia.core.models import IngestRun, RunStatus


def execute_ingest_run(db: Session, ingest_run_id: str) -> None:
    row = db.get(IngestRun, ingest_run_id)
    if not row:
        return
    db.refresh(row)
    if row.status in (RunStatus.completed.value, RunStatus.failed.value):
        return
    settings = get_settings()
    base = row.target_url or settings.gopedia_base_url
    row.status = RunStatus.running.value
    row.started_at = datetime.utcnow()
    db.commit()

    client = GopediaClient(base)
    try:
        if row.ingest_mode == "sync":
            resp = client.ingest_sync(row.source_path, row.project_id)
            row.gopedia_request_id = resp.get("request_id")
            ok = resp.get("ok", False)
            row.stdout = resp.get("stdout") or json.dumps(resp)[:8000]
            row.stderr = resp.get("stderr") or resp.get("error")
            if resp.get("failure"):
                row.failure_json = resp["failure"] if isinstance(resp["failure"], dict) else {"raw": str(resp["failure"])}
            if ok:
                row.status = RunStatus.completed.value
            else:
                row.status = RunStatus.failed.value
                if not row.failure_json:
                    row.failure_json = {"message": resp.get("error") or "ingest failed"}
        else:
            idem = row.idempotency_key or str(uuid.uuid4())
            resp = client.ingest_job_create(row.source_path, row.project_id, idempotency_key=idem)
            row.gopedia_request_id = resp.get("request_id")
            job_id = resp.get("job_id")
            row.gopedia_job_id = job_id
            if not job_id:
                row.status = RunStatus.failed.value
                row.failure_json = {"message": "no job_id", "response": resp}
                row.ended_at = datetime.utcnow()
                db.commit()
                return

            deadline = time.monotonic() + settings.default_ingest_poll_timeout_s
            final: dict = {}
            while time.monotonic() < deadline:
                final = client.ingest_job_status(job_id)
                st = final.get("status", "")
                if st in ("completed", "failed"):
                    break
                time.sleep(settings.default_ingest_poll_interval_s)

            row.stdout = json.dumps(final.get("result") or final)[:8000]
            if final.get("failure"):
                row.failure_json = final["failure"]
            if final.get("status") == "completed":
                row.status = RunStatus.completed.value
            elif final.get("status") == "failed":
                row.status = RunStatus.failed.value
            else:
                row.status = RunStatus.failed.value
                row.failure_json = {"message": "ingest poll timeout", "last": final}
    except Exception as e:
        row.status = RunStatus.failed.value
        row.failure_json = {"message": str(e)}
        row.stderr = str(e)[:4000]
    finally:
        row.ended_at = datetime.utcnow()
        client.close()
        db.commit()
