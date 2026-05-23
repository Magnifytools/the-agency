"""Backfill task.project_id for orphan tasks.

For every task with project_id IS NULL, if the client has exactly ONE active
project, set task.project_id to that project's id.

Tasks with a client that has zero or multiple active projects are skipped (we
cannot infer the right project unambiguously).

Usage:
  python -m backend.scripts.backfill_task_projects             # dry-run (default)
  python -m backend.scripts.backfill_task_projects --apply     # apply changes
  python -m backend.scripts.backfill_task_projects --client-id 1 --apply  # scope to one client

Notes:
- Idempotent: tasks already linked to a project are never touched.
- "Active project" = Project.status == "active".
- Soft-deleted clients (status == "finished") are excluded.
"""
import argparse
import asyncio
from collections import defaultdict

from sqlalchemy import select, update

from backend.db.database import async_session
from backend.db.models import Client, Project, Task


async def main(apply: bool, scope_client_id: int | None) -> None:
    async with async_session() as db:
        # 1. Fetch active clients (optionally scoped to one)
        clients_stmt = select(Client).where(Client.status != "finished")
        if scope_client_id is not None:
            clients_stmt = clients_stmt.where(Client.id == scope_client_id)
        clients_result = await db.execute(clients_stmt)
        clients = list(clients_result.scalars().all())

        # 2. For each client, find their active projects
        client_to_active_projects: dict[int, list[Project]] = defaultdict(list)
        if clients:
            proj_stmt = select(Project).where(
                Project.client_id.in_([c.id for c in clients]),
                Project.status == "active",
            )
            proj_result = await db.execute(proj_stmt)
            for p in proj_result.scalars().all():
                client_to_active_projects[p.client_id].append(p)

        # 3. For each client with exactly one active project, find orphan tasks
        plan: list[tuple[int, str, int, int, str]] = []  # (task_id, task_title, client_id, project_id, project_name)
        skipped_zero = 0
        skipped_multi = 0

        for client in clients:
            projects = client_to_active_projects.get(client.id, [])
            if len(projects) == 0:
                # Count orphan tasks of this client so we can report
                orphan_count_stmt = select(Task.id).where(
                    Task.client_id == client.id,
                    Task.project_id.is_(None),
                )
                orphan_count_result = await db.execute(orphan_count_stmt)
                skipped_zero += len(list(orphan_count_result.scalars().all()))
                continue
            if len(projects) > 1:
                orphan_count_stmt = select(Task.id).where(
                    Task.client_id == client.id,
                    Task.project_id.is_(None),
                )
                orphan_count_result = await db.execute(orphan_count_stmt)
                skipped_multi += len(list(orphan_count_result.scalars().all()))
                continue

            only_project = projects[0]
            tasks_stmt = select(Task).where(
                Task.client_id == client.id,
                Task.project_id.is_(None),
            )
            tasks_result = await db.execute(tasks_stmt)
            for t in tasks_result.scalars().all():
                plan.append((t.id, t.title, client.id, only_project.id, only_project.name))

        # 4. Report
        by_project: dict[tuple[int, str], int] = defaultdict(int)
        for _, _, _, pid, pname in plan:
            by_project[(pid, pname)] += 1

        print("=" * 72)
        print(f"Backfill task→project (apply={apply})")
        print("=" * 72)
        print(f"Tasks that will be linked: {len(plan)}")
        for (pid, pname), n in sorted(by_project.items(), key=lambda kv: -kv[1]):
            print(f"  • project #{pid} {pname!r}: {n} tasks")
        print()
        print(f"Skipped (client has 0 active projects, manual assignment needed): {skipped_zero}")
        print(f"Skipped (client has multiple active projects, ambiguous):       {skipped_multi}")
        print("=" * 72)

        if not plan:
            print("Nothing to do.")
            return

        if not apply:
            print("Dry-run only. Re-run with --apply to commit changes.")
            return

        # 5. Apply in a single bulk update per project (for efficiency)
        per_project: dict[int, list[int]] = defaultdict(list)
        for task_id, _, _, project_id, _ in plan:
            per_project[project_id].append(task_id)

        for project_id, task_ids in per_project.items():
            await db.execute(
                update(Task)
                .where(Task.id.in_(task_ids))
                .values(project_id=project_id)
            )
        await db.commit()
        print(f"✓ Linked {len(plan)} tasks across {len(per_project)} projects.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill task.project_id when client has 1 active project.")
    parser.add_argument("--apply", action="store_true", help="Actually commit the changes (default: dry-run)")
    parser.add_argument("--client-id", type=int, default=None, help="Restrict to a single client id")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(apply=args.apply, scope_client_id=args.client_id))
