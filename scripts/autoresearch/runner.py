#!/usr/bin/env python3
"""Agency PM AutoResearch Runner.

Autonomous loop that fetches Agency data, analyzes with Claude,
self-evaluates quality, and iterates to improve.

Usage:
    ANTHROPIC_API_KEY=sk-... python3 scripts/autoresearch/runner.py
    ANTHROPIC_API_KEY=sk-... python3 scripts/autoresearch/runner.py --iterations 5 --agency-url http://localhost:8004
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

try:
    import requests
    import anthropic
except ImportError:
    print("pip install requests anthropic")
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────

AGENCY_PROD_URL = "http://localhost:8004"
USER = {"email": "david@magnify.ing", "password": "Agency#David42"}

PROGRAM_PATH = Path(__file__).parent / "program.md"
OUTPUT_DIR = Path(__file__).parent / "output"


def login(agency_url: str) -> Optional[str]:
    """Login to Agency backend."""
    try:
        resp = requests.post(
            f"{agency_url}/api/auth/login",
            json=USER,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception as e:
        print(f"  Login error: {e}")
    return None


def fetch_data(agency_url: str, token: str, endpoints: List[str]) -> Dict:
    """Fetch data from multiple Agency endpoints."""
    headers = {"Authorization": f"Bearer {token}"}
    data = {}
    for ep in endpoints:
        try:
            resp = requests.get(f"{agency_url}{ep}", headers=headers, timeout=15)
            if resp.status_code == 200:
                data[ep] = resp.json()
            else:
                data[ep] = {"error": resp.status_code}
        except Exception as e:
            data[ep] = {"error": str(e)[:80]}
    return data


def analyze_with_claude(program: str, data: Dict, iteration: int, previous_findings: List[Dict]) -> Dict:
    """Send data to Claude for PM analysis. Returns finding dict."""
    client = anthropic.Anthropic()

    prev_text = ""
    if previous_findings:
        prev_text = "\n\nHallazgos anteriores (mejorar sobre estos, no repetir):\n"
        for f in previous_findings:
            prev_text += f"- [{f.get('score', '?')}/10] {f.get('title', '?')}: {f.get('summary', '')[:100]}\n"

    prompt = f"""Eres un Project Manager senior de agencia digital. Iteración {iteration} del análisis.

{program}

## Datos actuales:
```json
{json.dumps(data, indent=2, default=str)[:8000]}
```
{prev_text}

Genera UN hallazgo accionable basado en los datos. Formato JSON exacto:
{{
  "title": "Título del hallazgo (máx 80 chars)",
  "summary": "Resumen en 2-3 frases con datos concretos",
  "data_points": ["dato1 con número", "dato2 con número"],
  "action": "Qué hacer exactamente (accionable y específico)",
  "priority": "high|medium|low",
  "self_score": {{
    "actionable": 1-3,
    "data_backed": 1-3,
    "urgent": 1-2,
    "impact": 1-2,
    "total": 1-10
  }}
}}

Solo JSON, nada más."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        return {"title": "Error en análisis", "summary": str(e)[:200], "self_score": {"total": 0}}


def run_iteration(
    agency_url: str,
    token: str,
    iteration: int,
    program: str,
    previous_findings: List[Dict],
) -> Dict:
    """Run one PM research iteration."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    if iteration == 1:
        # General state: dashboard + today tasks
        endpoints = [
            "/api/dashboard/overview",
            "/api/dashboard/today",
            "/api/tasks?status=pending&limit=50",
            "/api/inbox/count",
        ]
    elif iteration == 2:
        # Time analysis: 7-day time entries by client
        endpoints = [
            f"/api/time-entries/by-client?date_from={week_ago}&date_to={today}",
            f"/api/time-entries/by-project?date_from={week_ago}&date_to={today}",
            "/api/dashboard/overview",
        ]
    elif iteration == 3:
        # Stalled projects: projects + tasks
        endpoints = [
            "/api/projects",
            "/api/tasks?status=in_progress&limit=50",
            "/api/clients/health-scores",
        ]
    elif iteration == 4:
        # Workload balance: tasks per user
        endpoints = [
            "/api/tasks?status=pending&limit=100",
            "/api/tasks?status=in_progress&limit=100",
            f"/api/time-entries?date_from={week_ago}&date_to={today}&limit=200",
        ]
    else:
        # Synthesis: profitability + recommendations
        endpoints = [
            "/api/dashboard/overview",
            "/api/dashboard/profitability",
            "/api/billing/overdue",
            "/api/clients/health-scores",
        ]

    data = fetch_data(agency_url, token, endpoints)
    finding = analyze_with_claude(program, data, iteration, previous_findings)
    finding["iteration"] = iteration
    finding["timestamp"] = datetime.utcnow().isoformat()
    finding["endpoints_used"] = list(data.keys())

    return finding


def main():
    parser = argparse.ArgumentParser(description="Agency PM AutoResearch Runner")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--agency-url", default=AGENCY_PROD_URL)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Agency PM AutoResearch")
    print(f"Agency: {args.agency_url}")
    print(f"Iterations: {args.iterations}")
    print(f"Started: {datetime.utcnow().isoformat()}")

    # Read program
    program = PROGRAM_PATH.read_text()

    # Login
    token = login(args.agency_url)
    if not token:
        print("❌ Login failed")
        sys.exit(1)
    print("✅ Logged in\n")

    # Run iterations
    findings = []
    iteration_log = []

    for i in range(1, args.iterations + 1):
        print(f"{'─'*40}")
        print(f"  Iteration {i}/{args.iterations}")
        print(f"{'─'*40}")

        start = time.time()
        finding = run_iteration(args.agency_url, token, i, program, findings)
        elapsed = round(time.time() - start, 1)

        score = finding.get("self_score", {}).get("total", 0)
        title = finding.get("title", "?")
        print(f"  Score: {score}/10 | {title}")
        print(f"  Time: {elapsed}s")

        if score >= 7:
            findings.append(finding)
            print(f"  ✅ Accepted (score >= 7)")
        else:
            print(f"  ⚠️  Below threshold — will iterate")

        iteration_log.append({
            "iteration": i,
            "score": score,
            "accepted": score >= 7,
            "title": title,
            "elapsed_s": elapsed,
        })

    # Save outputs
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    findings_path = OUTPUT_DIR / f"findings_{ts}.json"
    with open(findings_path, "w") as f:
        json.dump(findings, f, indent=2, default=str)

    log_path = OUTPUT_DIR / f"iteration_log_{ts}.json"
    with open(log_path, "w") as f:
        json.dump(iteration_log, f, indent=2, default=str)

    # Generate weekly brief
    report_lines = [
        f"# Agency PM Weekly Brief",
        f"> Generated: {datetime.utcnow().isoformat()}",
        f"> Iterations: {args.iterations} | Accepted findings: {len(findings)}/{args.iterations}",
        "",
        "---",
        "",
    ]
    for idx, f_item in enumerate(findings, 1):
        score = f_item.get("self_score", {}).get("total", "?")
        report_lines.extend([
            f"## {idx}. {f_item.get('title', '?')} (score: {score}/10)",
            "",
            f_item.get("summary", ""),
            "",
            "**Datos:**",
        ])
        for dp in f_item.get("data_points", []):
            report_lines.append(f"- {dp}")
        report_lines.extend([
            "",
            f"**Acción:** {f_item.get('action', '?')}",
            f"**Prioridad:** {f_item.get('priority', '?')}",
            "",
            "---",
            "",
        ])

    report_path = OUTPUT_DIR / f"weekly_brief_{ts}.md"
    report_path.write_text("\n".join(report_lines))

    # Summary
    avg_score = sum(il["score"] for il in iteration_log) / len(iteration_log) if iteration_log else 0
    print(f"\n{'='*40}")
    print(f"  RESULTS")
    print(f"{'='*40}")
    print(f"  Iterations: {args.iterations}")
    print(f"  Accepted findings: {len(findings)}")
    print(f"  Avg score: {avg_score:.1f}/10")
    print(f"  Brief: {report_path}")
    print(f"  Findings: {findings_path}")


if __name__ == "__main__":
    main()
