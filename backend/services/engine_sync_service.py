"""Periodic sync of Engine SEO metrics into Agency cached columns."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from backend.config import settings
from backend.db.database import async_session
from backend.db.models import Client, ClientStatus

logger = logging.getLogger(__name__)


async def sync_engine_metrics() -> dict:
    """Fetch metrics from Engine for every linked client and cache them locally.

    Returns dict with ``synced`` and ``failed`` counts.
    """
    base = (settings.ENGINE_API_URL or "").rstrip("/")
    if not base or not settings.ENGINE_SERVICE_KEY:
        logger.warning("Engine sync skipped: ENGINE_API_URL or ENGINE_SERVICE_KEY not configured")
        return {"synced": 0, "failed": 0, "detail": "not configured"}

    headers = {"X-Service-Key": settings.ENGINE_SERVICE_KEY}
    synced = 0
    failed = 0

    async with async_session() as session:
        result = await session.execute(
            select(Client).where(
                Client.engine_project_id.isnot(None),
                Client.status == ClientStatus.active,
            )
        )
        clients = result.scalars().all()

        if not clients:
            logger.info("Engine sync: no linked clients found")
            return {"synced": 0, "failed": 0}

        logger.info("Engine sync: processing %d linked clients", len(clients))

        async with httpx.AsyncClient(timeout=15.0) as http:
            for client in clients:
                try:
                    url = f"{base}/api/integration/projects/{client.engine_project_id}/metrics"
                    resp = await http.get(url, headers=headers)
                    if resp.status_code != 200:
                        logger.warning(
                            "Engine sync: failed for client %d (project %d): HTTP %d",
                            client.id, client.engine_project_id, resp.status_code,
                        )
                        failed += 1
                        continue

                    data = resp.json()
                    client.engine_content_count = data.get("content_count")
                    client.engine_keyword_count = data.get("keyword_count")
                    client.engine_avg_position = data.get("avg_position")
                    client.engine_clicks_30d = data.get("clicks_30d")
                    client.engine_impressions_30d = data.get("impressions_30d")
                    client.engine_metrics_synced_at = datetime.now(timezone.utc)
                    synced += 1
                except Exception:
                    logger.exception(
                        "Engine sync: error for client %d (project %d)",
                        client.id, client.engine_project_id,
                    )
                    failed += 1

        await session.commit()

    logger.info("Engine sync done: synced=%d, failed=%d", synced, failed)
    return {"synced": synced, "failed": failed}
