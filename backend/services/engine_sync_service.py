"""Periodic, coherent Engine snapshots cached on linked Agency clients."""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update

from backend.config import settings
from backend.db.database import async_session
from backend.db.models import Client, ClientStatus

logger = logging.getLogger(__name__)


def _valid_snapshot(summary: object, alerts: object, project_id: int) -> bool:
    if not isinstance(summary, dict) or not isinstance(alerts, dict):
        return False
    required = {
        "project_id", "content_count", "keyword_count", "avg_position",
        "clicks_30d", "impressions_30d", "as_of", "period_start",
        "previous_period_start", "ranking_device", "observed_keyword_count",
        "keywords_top3", "keywords_top10", "keywords_top20",
        "inspected_count", "indexed_count",
    }
    if (
        not required.issubset(summary)
        or isinstance(summary["project_id"], bool)
        or not isinstance(summary["project_id"], int)
        or summary["project_id"] != project_id
    ):
        return False
    try:
        as_of = date.fromisoformat(summary["as_of"])
        period_start = date.fromisoformat(summary["period_start"])
        previous_period_start = date.fromisoformat(summary["previous_period_start"])
    except (TypeError, ValueError):
        return False
    if any(
        value.isoformat() != summary[key]
        for key, value in (
            ("as_of", as_of),
            ("period_start", period_start),
            ("previous_period_start", previous_period_start),
        )
    ):
        return False
    if period_start != as_of - timedelta(days=29) or previous_period_start != as_of - timedelta(days=59):
        return False
    alert_items = alerts.get("alerts")
    if (
        summary["ranking_device"] != "desktop"
        or isinstance(alerts.get("project_id"), bool)
        or alerts.get("project_id") != project_id
        or not isinstance(alert_items, list)
        or not all(isinstance(item, dict) for item in alert_items)
    ):
        return False
    for alert in alert_items:
        severity = alert.get("severity")
        alert_type = alert.get("type")
        title = alert.get("title")
        detail = alert.get("detail")
        detected_at = alert.get("detected_at")
        if (
            severity not in {"critical", "warning", "info"}
            or not isinstance(alert_type, str)
            or not alert_type
            or not isinstance(title, str)
            or not title
            or (detail is not None and not isinstance(detail, str))
            or (detected_at is not None and not isinstance(detected_at, str))
        ):
            return False
        if detected_at is not None:
            try:
                datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
            except ValueError:
                return False
    for key in (
        "content_count", "keyword_count", "observed_keyword_count",
        "keywords_top3", "keywords_top10", "keywords_top20",
        "inspected_count", "indexed_count", "clicks_30d", "impressions_30d",
    ):
        if isinstance(summary[key], bool) or not isinstance(summary[key], int) or summary[key] < 0:
            return False
    if not (
        summary["indexed_count"] <= summary["inspected_count"]
        and summary["observed_keyword_count"] <= summary["keyword_count"]
        and summary["keywords_top3"] <= summary["keywords_top10"]
        <= summary["keywords_top20"] <= summary["observed_keyword_count"]
    ):
        return False
    position = summary["avg_position"]
    return position is None or (isinstance(position, (int, float)) and not isinstance(position, bool) and math.isfinite(position) and position >= 0)


async def sync_engine_metrics() -> dict:
    """Fetch summary+alerts and atomically replace only a complete snapshot."""
    base = (settings.ENGINE_API_URL or "").rstrip("/")
    if not base or not settings.ENGINE_SERVICE_KEY:
        logger.warning("Engine sync skipped: ENGINE_API_URL or ENGINE_SERVICE_KEY not configured")
        return {"synced": 0, "failed": 0, "detail": "not configured"}

    headers = {"X-Service-Key": settings.ENGINE_SERVICE_KEY}
    synced = failed = 0
    async with async_session() as session:
        client_links = (await session.execute(select(Client.id, Client.engine_project_id).where(
            Client.engine_project_id.isnot(None), Client.status == ClientStatus.active,
        ))).all()
    if not client_links:
        return {"synced": 0, "failed": 0}

    async with httpx.AsyncClient(timeout=15.0) as http:
        for client_id, project_id in client_links:
            try:
                summary_response = await http.get(f"{base}/api/integration/projects/{project_id}/summary", headers=headers)
                alerts_response = await http.get(f"{base}/api/integration/projects/{project_id}/alerts", headers=headers)
                if summary_response.status_code != 200 or alerts_response.status_code != 200:
                    raise ValueError("non-success snapshot component")
                summary, alerts = summary_response.json(), alerts_response.json()
                if not _valid_snapshot(summary, alerts, project_id):
                    raise ValueError("invalid Engine snapshot")
                async with async_session() as session:
                    result = await session.execute(update(Client).where(
                        Client.id == client_id,
                        Client.engine_project_id == project_id,
                        Client.status == ClientStatus.active,
                    ).values(
                        engine_content_count=summary["content_count"], engine_keyword_count=summary["keyword_count"],
                        engine_avg_position=summary["avg_position"], engine_clicks_30d=summary["clicks_30d"],
                        engine_impressions_30d=summary["impressions_30d"], engine_summary_data=summary,
                        engine_alerts_data=alerts,
                        engine_metrics_synced_at=datetime.now(timezone.utc),
                    ))
                    if result.rowcount != 1:
                        await session.rollback()
                        raise ValueError("client link changed during Engine request")
                    await session.commit()
                synced += 1
            except Exception as exc:
                logger.warning("Engine sync: snapshot failed for client %d: %s", client_id, type(exc).__name__)
                failed += 1
    return {"synced": synced, "failed": failed}
