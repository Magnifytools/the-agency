"""Google Calendar integration — OAuth2 flow + event fetching."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from backend.config import settings
from backend.core.security import encrypt_vault_secret, decrypt_vault_secret

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _client_config() -> dict:
    """Build OAuth2 client config from env vars."""
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def get_auth_url(state: str = "") -> str:
    """Generate the Google OAuth2 authorization URL (no PKCE — server-side flow)."""
    from urllib.parse import urlencode
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens via direct HTTP (no PKCE)."""
    import httpx
    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        logger.error("Google token exchange failed: %s", resp.text)
        raise ValueError(f"Token exchange failed: {resp.status_code}")
    data = resp.json()
    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
    }


def _get_credentials(encrypted_refresh_token: str) -> Optional[Credentials]:
    """Build Credentials from an encrypted refresh token."""
    try:
        refresh_token = decrypt_vault_secret(encrypted_refresh_token) if encrypted_refresh_token.startswith("v1:") else encrypted_refresh_token
    except Exception:
        logger.warning("Failed to decrypt Google refresh token")
        return None

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )


def fetch_events(
    encrypted_refresh_token: str,
    calendar_id: str = "primary",
    time_min: datetime | None = None,
    time_max: datetime | None = None,
) -> list[dict]:
    """Fetch events from Google Calendar. Returns list of simplified event dicts."""
    from backend.services.temporal import business_zone
    creds = _get_credentials(encrypted_refresh_token)
    if not creds:
        raise ValueError("Calendar credentials unavailable")
    time_min = time_min or datetime.now(business_zone()).replace(hour=0, minute=0, second=0, microsecond=0)
    time_max = time_max or time_min + timedelta(days=2)
    if time_min.tzinfo is None:
        time_min = time_min.replace(tzinfo=business_zone())
    if time_max.tzinfo is None:
        time_max = time_max.replace(tzinfo=business_zone())
    service = build("calendar", "v3", credentials=creds)
    events, token, seen_tokens = [], None, set()
    while True:
        result = service.events().list(
            calendarId=calendar_id, timeMin=time_min.isoformat(), timeMax=time_max.isoformat(),
            singleEvents=True, showDeleted=True, orderBy="startTime", maxResults=250,
            **({"pageToken": token} if token else {}),
        ).execute()
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise ValueError("Incomplete calendar response")
        for item in result.get("items", []):
            if item.get("status") == "cancelled":
                events.append({"google_event_id": item["id"], "cancelled": True})
                continue
            start, end = item.get("start", {}), item.get("end", {})
            if not item.get("id") or not (start.get("dateTime") or start.get("date")):
                raise ValueError("Incomplete calendar event")
            events.append({
                "google_event_id": item["id"], "title": item.get("summary", "(Sin título)"),
                "description": item.get("description", ""), "start_time": start.get("dateTime") or start.get("date"),
                "end_time": end.get("dateTime") or end.get("date"), "is_all_day": "date" in start and "dateTime" not in start,
            })
        token = result.get("nextPageToken")
        if not token:
            return events
        if token in seen_tokens:
            raise ValueError("Calendar pagination repeated a token")
        seen_tokens.add(token)


def encrypt_refresh_token(token: str) -> str:
    """Encrypt a refresh token for storage."""
    return encrypt_vault_secret(token)
