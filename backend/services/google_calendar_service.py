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
    """Generate the Google OAuth2 authorization URL."""
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
    )
    return url


def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens. Returns {access_token, refresh_token}."""
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
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
    creds = _get_credentials(encrypted_refresh_token)
    if not creds:
        return []

    if not time_min:
        time_min = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if not time_max:
        time_max = time_min + timedelta(days=2)

    try:
        service = build("calendar", "v3", credentials=creds)
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat() + "Z",
            timeMax=time_max.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        ).execute()

        events = []
        for item in result.get("items", []):
            if item.get("status") == "cancelled":
                continue
            start = item.get("start", {})
            end = item.get("end", {})
            is_all_day = "date" in start and "dateTime" not in start

            events.append({
                "google_event_id": item["id"],
                "title": item.get("summary", "(Sin título)"),
                "description": item.get("description", ""),
                "start_time": start.get("dateTime") or start.get("date"),
                "end_time": end.get("dateTime") or end.get("date"),
                "is_all_day": is_all_day,
                "location": item.get("location", ""),
                "attendees": [
                    a.get("email", "") for a in item.get("attendees", [])
                    if not a.get("self", False)
                ],
            })

        return events

    except Exception as e:
        logger.error("Google Calendar fetch failed: %s", e)
        return []


def encrypt_refresh_token(token: str) -> str:
    """Encrypt a refresh token for storage."""
    return encrypt_vault_secret(token)
