#!/usr/bin/env python3
"""E2E smoke: SEO platform → CRM webhook → read-back API.

Usage (CRM running on localhost:8000):
  python scripts/seo_crm_smoke.py --crm http://localhost:8000 --secret dev-seo-secret
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request


def sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def post_json(url: str, payload: dict, secret: str = "") -> dict:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-SEO-Signature"] = sign(body, secret)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_json(url: str) -> dict | list:
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read())


def main() -> int:
    parser = argparse.ArgumentParser(description="SEO↔CRM integration smoke test")
    parser.add_argument("--crm", default="http://localhost:8000", help="CRM base URL")
    parser.add_argument("--secret", default="", help="AIOS_SEO_WEBHOOK_SECRET (optional)")
    parser.add_argument("--project-id", default="smoke-proj-001")
    args = parser.parse_args()

    base = args.crm.rstrip("/")
    ext_id = args.project_id

    steps: list[tuple[str, callable]] = []

    def step_link():
        post_json(
            f"{base}/marketing/seo/webhook",
            {
                "event_type": "marketing.seo.project.linked",
                "version": 1,
                "payload": {
                    "external_project_id": ext_id,
                    "name": "Smoke Test Project",
                    "domain": "smoke.example.com",
                    "region": "Москва",
                    "status": "active",
                },
            },
            args.secret,
        )

    def step_snapshot():
        post_json(
            f"{base}/marketing/seo/webhook",
            {
                "event_type": "marketing.seo.snapshot.updated",
                "version": 1,
                "payload": {
                    "external_project_id": ext_id,
                    "date": "2026-07-01",
                    "visibility": 55.5,
                    "total_keywords": 500,
                    "top10_count": 120,
                    "critical_tasks": 2,
                    "quick_wins": 5,
                    "payload": {"task_count": 10},
                },
            },
            args.secret,
        )

    def step_verify():
        projects = get_json(f"{base}/marketing/seo/projects")
        match = [p for p in projects if p.get("external_project_id") == ext_id or p.get("externalProjectId") == ext_id]
        if not match:
            raise RuntimeError("project not found after webhook")
        pid = match[0].get("id")
        detail = get_json(f"{base}/marketing/seo/projects/{pid}")
        name = detail.get("name") or detail.get("Name")
        if name != "Smoke Test Project":
            raise RuntimeError(f"unexpected project name: {name}")
        summary = get_json(f"{base}/marketing/seo/projects/summary")
        if summary.get("totalProjects", 0) < 1:
            raise RuntimeError("summary empty")

    for label, fn in [
        ("link project", step_link),
        ("push snapshot", step_snapshot),
        ("verify read-back", step_verify),
    ]:
        try:
            fn()
            print(f"OK  {label}")
        except urllib.error.HTTPError as exc:
            print(f"FAIL {label}: HTTP {exc.code} {exc.read().decode()}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"FAIL {label}: {exc}", file=sys.stderr)
            return 1

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
