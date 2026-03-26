#!/usr/bin/env python3
"""Agency Evaluator — Automated QA for The Agency.

Inspired by Anthropic's Harness (Planner→Generator→Evaluator pattern).
Tests all critical endpoints as both admin and member user.
Outputs a score 0-100 per module and overall.

Usage:
    python3 scripts/evaluator.py [--base-url https://agency.magnifytools.com]
"""
import argparse
import json
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────

USERS = {
    "admin": {"email": "david@magnify.ing", "password": "Agency#David42"},
    "member": {"email": "nacho@magnify.ing", "password": "Magnify2026!"},
}

# Module → list of (method, path, expected_status, description)
MODULES = {
    "auth": [
        ("POST", "/api/auth/login", 200, "Login"),
        ("GET", "/api/auth/me", 200, "Current user"),
    ],
    "dashboard": [
        ("GET", "/api/dashboard/overview", 200, "Dashboard overview"),
        ("GET", "/api/dashboard/today", 200, "Today tasks"),
    ],
    "tasks": [
        ("GET", "/api/tasks?page_size=5", 200, "List tasks"),
        ("POST", "/api/tasks", 201, "Create task", {"title": "__EVAL_TEST__"}),
    ],
    "timer": [
        ("GET", "/api/timer/active", 200, "Active timer"),
    ],
    "time_entries": [
        ("GET", "/api/time-entries?page_size=5", 200, "List time entries"),
    ],
    "clients": [
        ("GET", "/api/clients?page_size=5", 200, "List clients"),
    ],
    "projects": [
        ("GET", "/api/projects?page_size=5", 200, "List projects"),
    ],
    "inbox": [
        ("GET", "/api/inbox?page_size=5", 200, "List inbox"),
        ("GET", "/api/inbox/count", 200, "Inbox count"),
    ],
    "notifications": [
        ("GET", "/api/notifications?page_size=5", 200, "List notifications"),
        ("GET", "/api/notifications/unread-count", 200, "Unread count"),
    ],
    "users": [
        ("GET", "/api/users", 200, "List users"),
    ],
    "digests": [
        ("GET", "/api/digests?page_size=5", 200, "List digests"),
    ],
    "reports": [
        ("GET", "/api/reports?page_size=5", 200, "List reports"),
    ],
    "pm": [
        ("GET", "/api/pm/insights", 200, "List insights"),
    ],
    "leads": [
        ("GET", "/api/leads?page_size=5", 200, "List leads"),
    ],
    "vault": [
        ("GET", "/api/vault/assets", 200, "List vault assets (admin only)"),
    ],
}

# Modules that should be blocked for member
ADMIN_ONLY_MODULES = {"vault"}


def login(base_url: str, email: str, password: str) -> Optional[str]:
    """Login and return JWT token."""
    try:
        resp = requests.post(
            f"{base_url}/api/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception as e:
        print(f"  LOGIN FAILED: {e}")
    return None


def test_endpoint(
    base_url: str,
    token: str,
    method: str,
    path: str,
    expected_status: int,
    description: str,
    body: Optional[dict] = None,
) -> Dict:
    """Test a single endpoint. Returns result dict."""
    url = f"{base_url}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    start = time.time()

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=15)
        elif method == "POST":
            resp = requests.post(url, headers=headers, json=body or {}, timeout=15)
        elif method == "PUT":
            resp = requests.put(url, headers=headers, json=body or {}, timeout=15)
        elif method == "DELETE":
            resp = requests.delete(url, headers=headers, timeout=15)
        else:
            return {"pass": False, "error": f"Unknown method {method}"}

        elapsed = round((time.time() - start) * 1000)
        passed = resp.status_code == expected_status

        result = {
            "pass": passed,
            "status": resp.status_code,
            "expected": expected_status,
            "elapsed_ms": elapsed,
            "description": description,
            "path": path,
        }

        if not passed:
            try:
                result["detail"] = resp.json().get("detail", "")[:100]
            except Exception:
                result["detail"] = resp.text[:100]

        return result

    except requests.Timeout:
        return {"pass": False, "error": "TIMEOUT", "description": description, "path": path}
    except Exception as e:
        return {"pass": False, "error": str(e)[:100], "description": description, "path": path}


def cleanup_test_data(base_url: str, token: str):
    """Delete any test data created during evaluation."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.get(f"{base_url}/api/tasks?page_size=100", headers=headers, timeout=10)
        if resp.status_code == 200:
            tasks = resp.json().get("items", [])
            for t in tasks:
                if t.get("title", "").startswith("__EVAL_"):
                    requests.delete(f"{base_url}/api/tasks/{t['id']}", headers=headers, timeout=5)
    except Exception:
        pass


def evaluate_user(base_url: str, role: str, email: str, password: str) -> Dict:
    """Run full evaluation for one user."""
    print(f"\n{'='*50}")
    print(f"  Evaluating: {role} ({email})")
    print(f"{'='*50}")

    token = login(base_url, email, password)
    if not token:
        return {"role": role, "score": 0, "error": "Login failed", "modules": {}}

    module_scores = {}
    all_results = []

    for module_name, endpoints in MODULES.items():
        results = []
        is_admin_only = module_name in ADMIN_ONLY_MODULES

        for endpoint in endpoints:
            method, path, expected, desc = endpoint[0], endpoint[1], endpoint[2], endpoint[3]
            body = endpoint[4] if len(endpoint) > 4 else None

            # For admin-only modules tested as member, expect 403
            if is_admin_only and role == "member":
                expected = 403

            result = test_endpoint(base_url, token, method, path, expected, desc, body)
            results.append(result)

            status_icon = "✅" if result["pass"] else "❌"
            status_code = result.get("status", "ERR")
            elapsed = result.get("elapsed_ms", "?")
            print(f"  {status_icon} {desc:35} {status_code:>4} ({elapsed}ms)")

        passed = sum(1 for r in results if r["pass"])
        total = len(results)
        score = round(passed / total * 100) if total else 0
        module_scores[module_name] = {"score": score, "passed": passed, "total": total, "results": results}
        all_results.extend(results)

    # Overall score
    total_passed = sum(1 for r in all_results if r["pass"])
    total_tests = len(all_results)
    overall_score = round(total_passed / total_tests * 100) if total_tests else 0

    # Cleanup
    cleanup_test_data(base_url, token)

    return {
        "role": role,
        "score": overall_score,
        "passed": total_passed,
        "total": total_tests,
        "modules": module_scores,
    }


def main():
    parser = argparse.ArgumentParser(description="Agency Evaluator")
    parser.add_argument("--base-url", default="https://agency.magnifytools.com")
    parser.add_argument("--output", default="scripts/evaluation-report.json")
    args = parser.parse_args()

    print(f"Agency Evaluator — {args.base_url}")
    print(f"Started: {datetime.utcnow().isoformat()}")

    results = {}
    for role, creds in USERS.items():
        results[role] = evaluate_user(args.base_url, role, creds["email"], creds["password"])

    # Summary
    print(f"\n{'='*50}")
    print("  SUMMARY")
    print(f"{'='*50}")
    for role, data in results.items():
        icon = "🟢" if data["score"] >= 90 else "🟡" if data["score"] >= 70 else "🔴"
        print(f"  {icon} {role:8} {data['score']:3}/100  ({data.get('passed',0)}/{data.get('total',0)} tests)")
        for mod, mod_data in data.get("modules", {}).items():
            if mod_data["score"] < 100:
                print(f"     ⚠️  {mod}: {mod_data['score']}/100 ({mod_data['passed']}/{mod_data['total']})")

    # Overall
    all_scores = [d["score"] for d in results.values()]
    overall = round(sum(all_scores) / len(all_scores)) if all_scores else 0
    icon = "🟢" if overall >= 90 else "🟡" if overall >= 70 else "🔴"
    print(f"\n  {icon} OVERALL: {overall}/100")

    # Save report
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "base_url": args.base_url,
        "overall_score": overall,
        "users": results,
    }
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Report saved to {args.output}")

    # Exit code based on score
    sys.exit(0 if overall >= 80 else 1)


if __name__ == "__main__":
    main()
