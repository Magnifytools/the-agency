"""Backfill task.project_id for orphan tasks.

For every task with project_id IS NULL, if the client has exactly ONE active
project, set task.project_id to that project's id.

Tasks with a client that has zero or multiple active projects are skipped (we
cannot infer the right project unambiguously), and so are tasks without a
client: nothing in the row says whose work they were.

Usage:
  python -m backend.scripts.backfill_task_projects             # dry-run (default)
  python -m backend.scripts.backfill_task_projects --apply     # apply changes
  python -m backend.scripts.backfill_task_projects --client-id 1 --apply  # scope to one client

Notes:
- Idempotent: tasks already linked to a project are never touched.
- "Active project" = Project.status == "active".
- Soft-deleted clients (status == "finished") are excluded.
- The bulk UPDATE bypasses the change journal, so Undo cannot revert it.
  ``--apply`` writes a JSON file with every linked task id first; reverting is
  ``UPDATE tasks SET project_id = NULL WHERE id IN (...)`` with those ids.
"""
import argparse
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update

from backend.db.database import async_session
from backend.db.models import Client, ClientStatus, Project, ProjectStatus, Task


async def build_plan(db, scope_client_id: int | None) -> dict:
    """Read-only: decide which orphan task goes to which project."""
    orphans_stmt = select(Task.id, Task.title, Task.client_id, Task.created_at).where(Task.project_id.is_(None))
    if scope_client_id is not None:
        orphans_stmt = orphans_stmt.where(Task.client_id == scope_client_id)
    orphans = (await db.execute(orphans_stmt.order_by(Task.id))).all()

    client_ids = {o.client_id for o in orphans if o.client_id is not None}
    open_clients: set[int] = set()
    active_projects: dict[int, list[tuple]] = defaultdict(list)
    if client_ids:
        open_clients = set((await db.execute(select(Client.id).where(
            Client.id.in_(client_ids), Client.status != ClientStatus.finished,
        ))).scalars().all())
        for project_id, project_name, client_id, project_created in (await db.execute(
            select(Project.id, Project.name, Project.client_id, Project.created_at).where(
                Project.client_id.in_(client_ids), Project.status == ProjectStatus.active,
            ).order_by(Project.id)
        )).all():
            active_projects[client_id].append((project_id, project_name, project_created))

    plan: list[tuple[int, str, int, int, str]] = []  # (task_id, title, client_id, project_id, project_name)
    skipped = {"no_client": 0, "finished_client": 0, "zero_projects": 0, "multiple_projects": 0}
    # Linked anyway, but worth a look: older work may belong to a closed project.
    predates_project = 0
    for orphan in orphans:
        if orphan.client_id is None:
            skipped["no_client"] += 1
        elif orphan.client_id not in open_clients:
            skipped["finished_client"] += 1
        elif not active_projects[orphan.client_id]:
            skipped["zero_projects"] += 1
        elif len(active_projects[orphan.client_id]) > 1:
            skipped["multiple_projects"] += 1
        else:
            project_id, project_name, project_created = active_projects[orphan.client_id][0]
            if orphan.created_at and project_created and orphan.created_at < project_created:
                predates_project += 1
            plan.append((orphan.id, orphan.title, orphan.client_id, project_id, project_name))
    return {"orphans": len(orphans), "plan": plan, "skipped": skipped, "predates_project": predates_project}


def print_report(result: dict, apply: bool) -> None:
    plan, skipped = result["plan"], result["skipped"]
    by_project: dict[tuple[int, str], int] = defaultdict(int)
    for _, _, _, pid, pname in plan:
        by_project[(pid, pname)] += 1

    print("=" * 72)
    print(f"Backfill task→project (apply={apply})")
    print("=" * 72)
    print(f"Tasks without project: {result['orphans']}")
    print(f"Tasks that will be linked: {len(plan)}")
    for (pid, pname), n in sorted(by_project.items(), key=lambda kv: -kv[1]):
        print(f"  • project #{pid} {pname!r}: {n} tasks")
    print(f"  of which created before their project existed (review!): {result['predates_project']}")
    print()
    print(f"Skipped (task has no client, nothing to infer from):            {skipped['no_client']}")
    print(f"Skipped (client is finished):                                   {skipped['finished_client']}")
    print(f"Skipped (client has 0 active projects, manual assignment needed): {skipped['zero_projects']}")
    print(f"Skipped (client has multiple active projects, ambiguous):       {skipped['multiple_projects']}")
    print("=" * 72)


async def main(apply: bool, scope_client_id: int | None, rollback_dir: Path = Path(".")) -> dict:
    async with async_session() as db:
        result = await build_plan(db, scope_client_id)
        print_report(result, apply)
        plan = result["plan"]

        if not plan:
            print("Nothing to do.")
            return result

        if not apply:
            await db.rollback()
            print("Dry-run only. Re-run with --apply to commit changes.")
            return result

        per_project: dict[int, list[int]] = defaultdict(list)
        for task_id, _, _, project_id, _ in plan:
            per_project[project_id].append(task_id)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rollback = rollback_dir / f"backfill_task_projects-{stamp}.json"
        rollback.write_text(json.dumps({
            "linked_task_ids_by_project": {str(k): v for k, v in per_project.items()},
            "revert_sql": "UPDATE tasks SET project_id = NULL WHERE id IN (<ids>) AND project_id = <project>",
        }, indent=2))
        result["rollback_file"] = rollback

        # Only rows that are still orphans: a task linked meanwhile is left alone.
        for project_id, task_ids in per_project.items():
            await db.execute(
                update(Task)
                .where(Task.id.in_(task_ids), Task.project_id.is_(None))
                .values(project_id=project_id)
            )
        await db.commit()
        print(f"✓ Linked {len(plan)} tasks across {len(per_project)} projects. Rollback ids: {rollback}")
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill task.project_id when client has 1 active project.")
    parser.add_argument("--apply", action="store_true", help="Actually commit the changes (default: dry-run)")
    parser.add_argument("--client-id", type=int, default=None, help="Restrict to a single client id")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(apply=args.apply, scope_client_id=args.client_id))
