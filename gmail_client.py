"""Gmail API client with OAuth2 refresh token support."""

import base64
import datetime as dt
import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import PDF_DIR, ROOT
from utils import clean_text


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT_SECRET_FILE = ROOT / "client_secret_282435778093-ig0kthatbvmprvbq6qg89inh74cbog2b.apps.googleusercontent.com.json"
TOKEN_FILE = ROOT / "token.json"


def _load_client_secret() -> dict:
    """Load client secret, handling both 'web' and 'installed' types."""
    with open(CLIENT_SECRET_FILE) as f:
        data = json.load(f)
    if "web" in data:
        return data["web"]
    if "installed" in data:
        return data["installed"]
    raise ValueError("Unknown client_secret format")


def _get_credentials() -> Credentials:
    """Load or create credentials. Handles token refresh automatically."""
    creds = None
    
    # Load existing token
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    
    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        print("[gmail] Refreshing access token...")
        creds.refresh(Request())
        # Save refreshed token
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    
    if not creds or not creds.valid:
        raise RuntimeError(
            "No valid Gmail credentials.\n"
            "Please run: python auth.py\n"
            "This will open a browser for OAuth authentication."
        )
    
    return creds


def _get_service():
    """Build Gmail service with fresh credentials."""
    creds = _get_credentials()
    return build("gmail", "v1", credentials=creds)


def test_connection() -> dict:
    """Quick test: fetch profile info to verify auth works."""
    service = _get_service()
    profile = service.users().getProfile(userId="me").execute()
    return {
        "email": profile.get("emailAddress"),
        "messages_total": profile.get("messagesTotal"),
        "threads_total": profile.get("threadsTotal"),
    }


def fetch_statement_emails(
    senders: list[str],
    days_back: int = 3,
    max_results: int = 50,
) -> list[dict]:
    """Search Gmail for emails from known senders with PDFs."""
    service = _get_service()
    after_date = (dt.datetime.utcnow() - dt.timedelta(days=days_back)).strftime("%Y/%m/%d")

    from_clause = " OR ".join(f"from:{s}" for s in senders)
    query = f"has:attachment filename:pdf ({from_clause}) after:{after_date}"

    results = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    messages = results.get("messages", [])
    emails: list[dict] = []

    for msg_meta in messages:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_meta["id"], format="full")
            .execute()
        )
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

        sender = headers.get("from", "")
        subject = headers.get("subject", "")
        date_ts = int(msg.get("internalDate", 0)) / 1000
        date_str = dt.datetime.utcfromtimestamp(date_ts).isoformat()

        # walk parts for attachments
        attachments = _list_attachments(payload)
        if not attachments:
            continue

        emails.append(
            {
                "id": msg_meta["id"],
                "sender": sender,
                "subject": subject,
                "date": date_str,
                "attachments": attachments,
                "snippet": clean_text(msg.get("snippet", "")),
            }
        )
    return emails


def _list_attachments(payload: dict) -> list[dict]:
    """Recursively find PDF attachments in a message payload."""
    attachments: list[dict] = []
    mime_type = payload.get("mimeType", "")

    if mime_type == "multipart/mixed" or mime_type.startswith("multipart/"):
        for part in payload.get("parts", []):
            attachments.extend(_list_attachments(part))
    elif payload.get("filename", "").lower().endswith(".pdf"):
        attachments.append(
            {
                "filename": payload["filename"],
                "attachment_id": payload.get("body", {}).get("attachmentId"),
                "size": payload.get("body", {}).get("size", 0),
            }
        )
    return attachments


def download_pdf(message_id: str, attachment_id: str, dest_path: Path) -> Path | None:
    """Download a PDF attachment and save locally."""
    service = _get_service()
    try:
        att = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = base64.urlsafe_b64decode(att["data"])
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(data)
        return dest_path
    except Exception as exc:
        print(f"Download failed for {message_id}/{attachment_id}: {exc}")
        return None


def fetch_emails_by_query(query: str, max_results: int = 30) -> list[dict]:
    """Generic email fetcher (used by payment detector / manual checks)."""
    service = _get_service()
    results = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    emails: list[dict] = []
    for msg_meta in results.get("messages", []):
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_meta["id"], format="metadata")
            .execute()
        )
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        emails.append(
            {
                "id": msg_meta["id"],
                "sender": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "snippet": msg.get("snippet", ""),
            }
        )
    return emails


def fetch_email_body_text(message_id: str) -> str:
    """Get plain text body of an email."""
    service = _get_service()
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    payload = msg.get("payload", {})
    return _extract_text_from_payload(payload)


def _extract_text_from_payload(payload: dict) -> str:
    """Recursively extract text/plain parts."""
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        return ""
    if mime_type.startswith("multipart/"):
        text_parts: list[str] = []
        for part in payload.get("parts", []):
            text_parts.append(_extract_text_from_payload(part))
        return "\n".join(text_parts)
    return ""
