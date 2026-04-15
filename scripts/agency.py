#!/usr/bin/env python3
"""CLI ligero para operar The Agency en producción desde terminal.

Uso básico:
    python scripts/agency.py login
    python scripts/agency.py tasks list --search taxfix
    python scripts/agency.py tasks close --search taxfix --status done
    python scripts/agency.py tasks close 1234

Guarda el token en ~/.agency_cli.json.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

import urllib.request
import urllib.parse
import urllib.error

API_BASE = os.environ.get("AGENCY_API_BASE", "https://agency.magnifytools.com/api")
STATE_FILE = Path.home() / ".agency_cli.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))
    STATE_FILE.chmod(0o600)


def _request(method: str, path: str, *, token: str | None = None, body: dict | None = None, params: dict | None = None) -> dict | list:
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def cmd_login(args):
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    resp = _request("POST", "/auth/login", body={"email": email, "password": password})
    token = resp.get("access_token")
    if not token:
        print("Login falló", file=sys.stderr)
        sys.exit(1)
    _save_state({"token": token, "email": email})
    print(f"OK — token guardado en {STATE_FILE}")


def _token() -> str:
    state = _load_state()
    t = state.get("token")
    if not t:
        print("No hay sesión. Ejecuta: agency login", file=sys.stderr)
        sys.exit(1)
    return t


def cmd_tasks_list(args):
    params = {"page_size": args.limit}
    if args.search:
        params["search"] = args.search
    if args.client:
        params["client_id"] = args.client
    if args.status:
        params["status"] = args.status
    resp = _request("GET", "/tasks", token=_token(), params=params)
    items = resp.get("items") if isinstance(resp, dict) else resp
    if not items:
        print("(sin tareas)")
        return
    for t in items:
        cid = t.get("client_id") or "—"
        status = t.get("status", "?")
        due = t.get("due_date") or ""
        print(f"#{t['id']:>5} [{status:>10}] {due:>10}  {t.get('title', '')[:70]}  (client={cid})")


def cmd_tasks_close(args):
    token = _token()
    status = args.status or "done"

    # Resolver IDs a cerrar
    ids: list[int] = []
    if args.ids:
        ids = [int(x) for x in args.ids]
    elif args.search:
        params = {"search": args.search, "page_size": 200}
        resp = _request("GET", "/tasks", token=token, params=params)
        items = resp.get("items") if isinstance(resp, dict) else resp
        # Filtrar por estado abierto por defecto
        open_states = {"todo", "in_progress", "blocked", "review"}
        if not args.all_states:
            items = [t for t in items if t.get("status") in open_states]
        ids = [t["id"] for t in items]

        if not ids:
            print("(sin tareas que coincidan)")
            return
        print("Se cerrarán:")
        for t in items:
            print(f"  #{t['id']}  {t.get('title', '')[:80]}")
        if not args.yes:
            ans = input("Confirmar? [y/N] ").strip().lower()
            if ans != "y":
                print("Cancelado.")
                return
    else:
        print("Usa --search o pasa IDs", file=sys.stderr)
        sys.exit(2)

    closed = 0
    for tid in ids:
        _request("PUT", f"/tasks/{tid}", token=token, body={"status": status})
        closed += 1
    print(f"✓ {closed} tareas actualizadas a {status}")


def main():
    p = argparse.ArgumentParser(prog="agency")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="Guardar token JWT").set_defaults(func=cmd_login)

    ptasks = sub.add_parser("tasks", help="Gestionar tareas")
    ptsub = ptasks.add_subparsers(dest="subcmd", required=True)

    pl = ptsub.add_parser("list")
    pl.add_argument("--search")
    pl.add_argument("--client", type=int)
    pl.add_argument("--status")
    pl.add_argument("--limit", type=int, default=50)
    pl.set_defaults(func=cmd_tasks_list)

    pc = ptsub.add_parser("close")
    pc.add_argument("ids", nargs="*", help="IDs específicos (opcional)")
    pc.add_argument("--search", help="Cerrar por coincidencia de título")
    pc.add_argument("--status", default="done", help="Estado destino (default: done)")
    pc.add_argument("--all-states", action="store_true", help="No filtrar por estados abiertos")
    pc.add_argument("-y", "--yes", action="store_true", help="Sin confirmación")
    pc.set_defaults(func=cmd_tasks_close)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
