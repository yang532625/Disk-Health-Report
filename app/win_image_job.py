# -*- coding: utf-8 -*-
"""Estado persistente de trabajos de imagen Windows."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

_JOB_STAGES = ("inventory", "winpe_ready", "captured", "iso_done")


def jobs_root() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DiskHealthReport", "win_image_jobs")


def _job_path(job_id: str) -> str:
    return os.path.join(jobs_root(), job_id, "job.json")


def new_job_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def job_dir(job_id: str) -> str:
    return os.path.join(jobs_root(), job_id)


def ensure_job_dir(job_id: str) -> str:
    path = job_dir(job_id)
    os.makedirs(path, exist_ok=True)
    return path


def load_job(job_id: str) -> dict[str, Any] | None:
    path = _job_path(job_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def save_job(job: dict[str, Any]) -> None:
    job_id = job.get("id") or new_job_id()
    job["id"] = job_id
    ensure_job_dir(job_id)
    path = _job_path(job_id)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(job, fh, indent=2, ensure_ascii=False)


def create_job() -> dict[str, Any]:
    job_id = new_job_id()
    ensure_job_dir(job_id)
    job = {
        "id": job_id,
        "stage": "inventory",
        "created": datetime.now(timezone.utc).isoformat(),
        "paths": {},
        "inventory": None,
    }
    save_job(job)
    return job


def list_jobs() -> list[dict[str, Any]]:
    root = jobs_root()
    if not os.path.isdir(root):
        return []
    jobs: list[dict[str, Any]] = []
    for name in sorted(os.listdir(root), reverse=True):
        job = load_job(name)
        if job:
            jobs.append(job)
    return jobs


def latest_job() -> dict[str, Any] | None:
    jobs = list_jobs()
    return jobs[0] if jobs else None


def set_stage(job: dict[str, Any], stage: str) -> dict[str, Any]:
    if stage in _JOB_STAGES:
        job["stage"] = stage
    save_job(job)
    return job


def inventory_path(job_id: str) -> str:
    return os.path.join(job_dir(job_id), "inventory.json")


def winget_export_path(job_id: str) -> str:
    return os.path.join(job_dir(job_id), "winget_packages.json")
