"""Core Update Keyword Shift Analyzer.

Compares top keywords from GSC before/after a core update using
semantic embeddings, PCA visualization, and KMeans clustering
to identify which themes were affected.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import httpx
import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

from backend.config import settings
from backend.services.ai_utils import get_anthropic_client, parse_claude_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers: Engine API
# ---------------------------------------------------------------------------


def _engine_headers() -> dict[str, str]:
    key = settings.ENGINE_SERVICE_KEY
    if not key:
        raise ValueError("ENGINE_SERVICE_KEY no configurada")
    return {"X-Service-Key": key}


def _engine_base() -> str:
    base = (settings.ENGINE_API_URL or "").rstrip("/")
    if not base:
        raise ValueError("ENGINE_API_URL no configurada")
    return base


async def get_top_keywords_for_period(
    project_id: int,
    date_start: str,
    date_end: str,
    top_n: int = 1000,
    metric: str = "clicks",
) -> dict[str, dict[str, Any]]:
    """Fetch top N keywords from The Engine for a date range.

    Returns: {keyword_text: {clicks, impressions, avg_position}}
    """
    base = _engine_base()
    url = f"{base}/api/integration/projects/{project_id}/keywords"
    params = {
        "from_date": date_start,
        "to_date": date_end,
        "top_n": top_n,
        "metric": metric,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url, headers=_engine_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()

    # Expect: {"keywords": [{"keyword": "...", "clicks": N, "impressions": N, "avg_position": F}]}
    result: dict[str, dict[str, Any]] = {}
    for kw in data.get("keywords", []):
        result[kw["keyword"]] = {
            "clicks": kw.get("clicks", 0),
            "impressions": kw.get("impressions", 0),
            "avg_position": kw.get("avg_position"),
        }
    return result


# ---------------------------------------------------------------------------
# Helpers: Voyage AI embeddings
# ---------------------------------------------------------------------------


async def batch_embed_keywords(
    keywords: list[str], batch_size: int = 128
) -> dict[str, list[float]]:
    """Embed keywords via Voyage AI (voyage-3) in batches."""
    api_key = settings.VOYAGE_API_KEY
    if not api_key:
        raise ValueError("VOYAGE_API_KEY no configurada")

    result: dict[str, list[float]] = {}
    url = "https://api.voyageai.com/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        for i in range(0, len(keywords), batch_size):
            batch = keywords[i : i + batch_size]
            payload = {"input": batch, "model": "voyage-3"}
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            for j, emb_obj in enumerate(data["data"]):
                result[batch[j]] = emb_obj["embedding"]

    return result


# ---------------------------------------------------------------------------
# Helpers: math / clustering
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def compute_centroid(embeddings: list[list[float]]) -> list[float]:
    return np.mean(np.array(embeddings), axis=0).tolist()


def centroid_distance(a: list[float], b: list[float]) -> float:
    return 1.0 - cosine_similarity(a, b)


def categorize_keywords(
    pre_kws: dict[str, Any], post_kws: dict[str, Any]
) -> tuple[set[str], set[str], set[str]]:
    """Return (lost, gained, retained) keyword sets."""
    pre_set = set(pre_kws.keys())
    post_set = set(post_kws.keys())
    lost = pre_set - post_set
    gained = post_set - pre_set
    retained = pre_set & post_set
    return lost, gained, retained


def cluster_keywords_by_theme(
    keywords: list[str],
    embeddings: dict[str, list[float]],
    n_clusters: int | None = None,
) -> list[dict[str, Any]]:
    """KMeans clustering on embeddings. Returns cluster info."""
    if len(keywords) < 3:
        return [{"representative": keywords[0] if keywords else "", "keywords": keywords}]

    vecs = np.array([embeddings[kw] for kw in keywords])

    if n_clusters is None:
        n_clusters = min(max(len(keywords) // 20, 3), 8)
    n_clusters = min(n_clusters, len(keywords))

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(vecs)

    clusters: list[dict[str, Any]] = []
    for c_idx in range(n_clusters):
        mask = labels == c_idx
        cluster_kws = [kw for kw, m in zip(keywords, mask) if m]
        if not cluster_kws:
            continue

        centroid = km.cluster_centers_[c_idx]
        # Find keyword closest to centroid
        best_kw = cluster_kws[0]
        best_dist = float("inf")
        for kw in cluster_kws:
            dist = float(np.linalg.norm(np.array(embeddings[kw]) - centroid))
            if dist < best_dist:
                best_dist = dist
                best_kw = kw

        clusters.append({"representative": best_kw, "keywords": cluster_kws})

    return clusters


def pca_reduce(
    all_keywords: list[str], embeddings: dict[str, list[float]]
) -> dict[str, tuple[float, float]]:
    """PCA to 2D for scatter plot."""
    if len(all_keywords) < 2:
        return {kw: (0.0, 0.0) for kw in all_keywords}

    vecs = np.array([embeddings[kw] for kw in all_keywords])
    n_components = min(2, vecs.shape[0], vecs.shape[1])
    pca = PCA(n_components=n_components)
    coords = pca.fit_transform(vecs)

    result: dict[str, tuple[float, float]] = {}
    for i, kw in enumerate(all_keywords):
        x = float(coords[i][0]) if n_components >= 1 else 0.0
        y = float(coords[i][1]) if n_components >= 2 else 0.0
        result[kw] = (x, y)
    return result


# ---------------------------------------------------------------------------
# Claude cluster labeling
# ---------------------------------------------------------------------------


async def label_theme_clusters(
    clusters: list[dict[str, Any]],
) -> list[str]:
    """Use Claude to generate 2-4 word labels for each cluster."""
    if not clusters:
        return []

    # Build prompt with cluster keywords
    cluster_descriptions = []
    for i, c in enumerate(clusters):
        sample = c["keywords"][:15]
        cluster_descriptions.append(f"Cluster {i + 1}: {', '.join(sample)}")

    prompt = (
        "Given these keyword clusters from a Google Search Console analysis, "
        "generate a short label (2-4 words) for each cluster that describes the topic/theme.\n\n"
        + "\n".join(cluster_descriptions)
        + "\n\nRespond with JSON: {\"labels\": [\"Label 1\", \"Label 2\", ...]}"
    )

    try:
        client = get_anthropic_client()
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        data = parse_claude_json(message)
        labels = data.get("labels", [])
        # Pad with fallback if needed
        while len(labels) < len(clusters):
            labels.append(clusters[len(labels)]["representative"])
        return labels
    except Exception:
        logger.warning("Failed to label clusters via Claude, using representative keywords")
        return [c["representative"] for c in clusters]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_core_update_analysis(
    project_id: int,
    pre_start: str,
    pre_end: str,
    post_start: str,
    post_end: str,
    top_n: int = 1000,
    metric: str = "clicks",
) -> dict[str, Any]:
    """Main orchestrator for core update keyword shift analysis."""

    # 1. Fetch keywords for both periods
    pre_kws = await get_top_keywords_for_period(
        project_id, pre_start, pre_end, top_n, metric
    )
    post_kws = await get_top_keywords_for_period(
        project_id, post_start, post_end, top_n, metric
    )

    if not pre_kws and not post_kws:
        return {
            "summary": {
                "pre_total_clicks": 0,
                "post_total_clicks": 0,
                "net_click_change": 0,
                "net_click_change_pct": 0,
                "centroid_distance": 0,
                "keywords_lost": 0,
                "keywords_gained": 0,
                "keywords_retained": 0,
            },
            "keywords": [],
            "themes_lost": [],
            "themes_gained": [],
        }

    # 2. Categorize
    lost, gained, retained = categorize_keywords(pre_kws, post_kws)

    # 3. Embed all unique keywords
    all_keywords = list(set(pre_kws.keys()) | set(post_kws.keys()))
    embeddings = await batch_embed_keywords(all_keywords)

    # 4. PCA reduce
    coords = pca_reduce(all_keywords, embeddings)

    # 5. Centroid distance
    pre_embs = [embeddings[kw] for kw in pre_kws if kw in embeddings]
    post_embs = [embeddings[kw] for kw in post_kws if kw in embeddings]
    pre_centroid = compute_centroid(pre_embs) if pre_embs else []
    post_centroid = compute_centroid(post_embs) if post_embs else []
    c_distance = (
        centroid_distance(pre_centroid, post_centroid)
        if pre_centroid and post_centroid
        else 0.0
    )

    # 6. Summary metrics
    metric_key = "clicks" if metric == "clicks" else "impressions"
    pre_total = sum(kw[metric_key] for kw in pre_kws.values())
    post_total = sum(kw[metric_key] for kw in post_kws.values())
    net_change = post_total - pre_total
    net_change_pct = round((net_change / pre_total * 100), 1) if pre_total > 0 else 0

    # 7. Build keyword list with coordinates
    keyword_list = []
    for kw in all_keywords:
        if kw in lost:
            category = "lost"
        elif kw in gained:
            category = "gained"
        else:
            category = "retained"

        clicks_pre = pre_kws.get(kw, {}).get("clicks", 0)
        clicks_post = post_kws.get(kw, {}).get("clicks", 0)
        x, y = coords.get(kw, (0.0, 0.0))

        keyword_list.append(
            {
                "keyword": kw,
                "category": category,
                "clicks_pre": clicks_pre,
                "clicks_post": clicks_post,
                "x": round(x, 4),
                "y": round(y, 4),
            }
        )

    # 8. Cluster lost & gained keywords by theme
    lost_list = sorted(lost, key=lambda k: pre_kws[k].get(metric_key, 0), reverse=True)
    gained_list = sorted(gained, key=lambda k: post_kws[k].get(metric_key, 0), reverse=True)

    themes_lost_raw = (
        cluster_keywords_by_theme(lost_list, embeddings)
        if len(lost_list) >= 3
        else [{"representative": kw, "keywords": [kw]} for kw in lost_list]
    )
    themes_gained_raw = (
        cluster_keywords_by_theme(gained_list, embeddings)
        if len(gained_list) >= 3
        else [{"representative": kw, "keywords": [kw]} for kw in gained_list]
    )

    # 9. Label clusters
    all_clusters = themes_lost_raw + themes_gained_raw
    labels = await label_theme_clusters(all_clusters)
    lost_labels = labels[: len(themes_lost_raw)]
    gained_labels = labels[len(themes_lost_raw) :]

    # 10. Format theme results
    def format_themes(
        clusters: list[dict], cluster_labels: list[str], kw_data: dict
    ) -> list[dict]:
        result = []
        for i, c in enumerate(clusters):
            label = cluster_labels[i] if i < len(cluster_labels) else c["representative"]
            total = sum(kw_data.get(kw, {}).get(metric_key, 0) for kw in c["keywords"])
            result.append(
                {
                    "theme_label": label,
                    "keywords": c["keywords"][:20],
                    "total_clicks": total,
                    "keyword_count": len(c["keywords"]),
                }
            )
        result.sort(key=lambda t: t["total_clicks"], reverse=True)
        return result

    themes_lost = format_themes(themes_lost_raw, lost_labels, pre_kws)
    themes_gained = format_themes(themes_gained_raw, gained_labels, post_kws)

    return {
        "summary": {
            "pre_total_clicks": pre_total,
            "post_total_clicks": post_total,
            "net_click_change": net_change,
            "net_click_change_pct": net_change_pct,
            "centroid_distance": round(c_distance, 4),
            "keywords_lost": len(lost),
            "keywords_gained": len(gained),
            "keywords_retained": len(retained),
        },
        "keywords": keyword_list,
        "themes_lost": themes_lost,
        "themes_gained": themes_gained,
    }
