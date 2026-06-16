"""
Polling worker mode for suu-auto.

Connects to the receipt-gatherer web app, claims automation jobs from the
queue, and fills the SU form using the shared FormExecutor engine.

Usage:
    suu poll

Environment variables:
    APP_URL              Base URL of the receipt-gatherer web app (required)
    WORKER_AUTH_TOKEN    Shared secret for Bearer-token auth with the API
    WORKER_ID            Identifier for this worker instance (default: hostname-pid)
    WORKER_DEFAULT_FORM_ID  Form to use when the job payload omits form_id (default: payment_request)
    SUU_HOME             Where suu keeps saved logins & downloads (default: ~/.suu)
    AUTH_MAX_AGE_DAYS    Reject saved logins older than this many days (default: 7)
    WORKER_POLL_INTERVAL_SECONDS      How often to check for jobs (default: 5)
    WORKER_HEARTBEAT_INTERVAL_SECONDS How often to send heartbeats (default: 15)
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
import traceback
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from suu.core.paths import playwright_state_file, suu_home
from suu.forms.executor import FormExecutor
from suu.forms.loader import definitions_dir, list_form_ids, load_form_definition
from suu.forms.payload import download_receipt, normalize_payload, resolve_receipt_urls
from suu.forms.schema import FormDefinition

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_URL = os.environ.get("APP_URL", "").rstrip("/")
WORKER_AUTH_TOKEN = os.environ.get("WORKER_AUTH_TOKEN", "")
WORKER_ID = os.environ.get("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"
HOST_NAME = socket.gethostname()

POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "5"))
HEARTBEAT_INTERVAL = int(os.environ.get("WORKER_HEARTBEAT_INTERVAL_SECONDS", "15"))
AUTH_MAX_AGE_DAYS = int(os.environ.get("AUTH_MAX_AGE_DAYS", "7"))

DOWNLOADS_DIR = suu_home() / "downloads"
# The worker shares the same saved login the form filler uses (~/.suu/playwright).
AUTH_FILE = playwright_state_file("default")

DEFAULT_FORM_ID = os.environ.get("WORKER_DEFAULT_FORM_ID", "payment_request")


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    if WORKER_AUTH_TOKEN:
        return {"Authorization": f"Bearer {WORKER_AUTH_TOKEN}"}
    return {}


async def _get(client: httpx.AsyncClient, path: str) -> dict:
    response = await client.get(f"{APP_URL}{path}", headers=_headers())
    response.raise_for_status()
    return response.json()


async def _post(client: httpx.AsyncClient, path: str, body: dict) -> None:
    await client.post(
        f"{APP_URL}{path}",
        json=body,
        headers={**_headers(), "Content-Type": "application/json"},
    )


async def send_heartbeat(
    client: httpx.AsyncClient,
    *,
    status: str,
    job_id: str | None = None,
) -> None:
    body: dict = {"workerId": WORKER_ID, "hostName": HOST_NAME, "status": status}
    if job_id:
        body["currentJobId"] = job_id
    try:
        await _post(client, "/api/worker/heartbeat", body)
    except Exception as exc:
        print(f"  ⚠  Heartbeat failed: {exc}")


async def poll_job(client: httpx.AsyncClient) -> dict | None:
    try:
        data = await _get(client, "/api/worker/poll")
        return data.get("job")
    except Exception as exc:
        print(f"  ⚠  Poll failed: {exc}")
        return None


async def report_done(client: httpx.AsyncClient, job_id: str, result: dict) -> None:
    try:
        await _post(client, f"/api/worker/jobs/{job_id}/done", {"result": result})
    except Exception as exc:
        print(f"  ⚠  report_done failed: {exc}")


async def report_failed(
    client: httpx.AsyncClient, job_id: str, error: str, details: dict
) -> None:
    try:
        await _post(
            client,
            f"/api/worker/jobs/{job_id}/fail",
            {"error": error, "details": details},
        )
    except Exception as exc:
        print(f"  ⚠  report_failed failed: {exc}")


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------

def _load_form(form_id: str) -> FormDefinition:
    try:
        return load_form_definition(form_id)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Form '{form_id}' not found. Available: {list_form_ids()}"
        )


async def run_job(job_id: str, payload: dict) -> dict:
    """
    Download the receipt, normalise the payload, and fill the form.
    The browser is left open for the user to review and submit manually.
    """
    form_id = payload.get("form_id") or DEFAULT_FORM_ID
    form_def = _load_form(form_id)

    # Download the first receipt image to a local file.
    urls = resolve_receipt_urls(payload)
    downloaded_file = None
    if urls:
        downloaded_file = await download_receipt(
            urls[0], DOWNLOADS_DIR / job_id, "receipt"
        )
        if not downloaded_file:
            print("  ⚠  Receipt download failed — form will be filled without file upload.")
    else:
        print("  ⚠  No receipt URL in payload — form will be filled without file upload.")

    form_data = normalize_payload(payload, downloaded_file)

    if not AUTH_FILE.exists() or AUTH_FILE.stat().st_size <= 50:
        raise RuntimeError(
            f"No saved login found at {AUTH_FILE}. "
            "Run `suu forms login` first."
        )

    auth_age_days = (time.time() - AUTH_FILE.stat().st_mtime) / 86400
    if auth_age_days > AUTH_MAX_AGE_DAYS:
        raise RuntimeError(
            f"Your saved login is {auth_age_days:.0f} days old (max {AUTH_MAX_AGE_DAYS}). "
            "Run `suu forms login` to refresh it."
        )

    executor = FormExecutor(headless=False)
    await executor.start()
    await executor.load_auth(str(AUTH_FILE))

    try:
        # Execute — the executor never submits, so we intentionally leave the
        # browser open for the treasurer to review and submit manually.
        await executor.execute(form_def, form_data)
    except Exception:
        await executor.stop()
        raise

    return {
        "success": True,
        "worker_id": WORKER_ID,
        "form_id": form_id,
        "receipt_downloaded": str(downloaded_file) if downloaded_file else None,
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_worker() -> None:
    if not APP_URL:
        raise RuntimeError(
            "APP_URL is required for poll mode. "
            "Set it in your environment or .env file."
        )

    print("suu worker ready")
    print(f"  id:    {WORKER_ID}")
    print(f"  app:   {APP_URL}")
    print(f"  auth:  {AUTH_FILE}")
    print(f"  forms: {definitions_dir()}")
    print()

    async with httpx.AsyncClient(timeout=30) as client:
        last_heartbeat = 0.0

        while True:
            now = time.monotonic()

            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                await send_heartbeat(client, status="idle")
                last_heartbeat = now

            job = await poll_job(client)
            if job is None:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            job_id = str(job["id"])
            payload: dict = job.get("payload_json") or {}
            print(f"→ Job {job_id}  (form: {payload.get('form_id') or DEFAULT_FORM_ID})")

            await send_heartbeat(client, status="busy", job_id=job_id)
            try:
                result = await run_job(job_id, payload)
                await report_done(client, job_id, result)
                print(f"✓ Job {job_id} filled — browser open for review and manual submit")
            except Exception as exc:
                print(f"✗ Job {job_id} failed: {exc}")
                await report_failed(
                    client,
                    job_id,
                    str(exc),
                    {"traceback": traceback.format_exc()},
                )
            finally:
                await send_heartbeat(client, status="idle")
                last_heartbeat = time.monotonic()
