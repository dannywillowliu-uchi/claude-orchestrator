"""Gmail API client for reading, drafting, and sending emails."""

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# Gmail scopes
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

DEFAULT_CREDENTIALS_FILE = "data/credentials/credentials.json"
DEFAULT_TOKEN_FILE = "data/credentials/gmail_token.json"


@dataclass
class Email:
    id: str
    thread_id: str
    subject: str
    sender: str
    to: str
    date: str
    snippet: str
    body: Optional[str] = None


@dataclass
class Draft:
    id: str
    message_id: str
    subject: str
    to: str
    body: str


class GmailClient:
    """Client for Gmail API operations."""

    def __init__(
        self,
        credentials_file: str = DEFAULT_CREDENTIALS_FILE,
        token_file: str = DEFAULT_TOKEN_FILE,
    ):
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self.creds: Optional[Credentials] = None
        self.service = None

    def authenticate(self) -> bool:
        """Authenticate with Gmail API."""
        if self.token_file.exists():
            self.creds = Credentials.from_authorized_user_file(
                str(self.token_file), GMAIL_SCOPES
            )

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except Exception as e:
                    print(f"Token refresh failed: {e}")
                    self.creds = None

            if not self.creds:
                if not self.credentials_file.exists():
                    print(f"Credentials file not found: {self.credentials_file}")
                    return False

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_file), GMAIL_SCOPES
                )
                self.creds = flow.run_local_server(port=0)

            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_file, "w") as token:
                token.write(self.creds.to_json())

        self.service = build("gmail", "v1", credentials=self.creds)
        return True

    def search_emails(
        self, query: str, max_results: int = 10
    ) -> list[Email]:
        """
        Search emails with Gmail query syntax.

        Examples:
            - "from:someone@example.com"
            - "subject:meeting"
            - "is:unread"
            - "newer_than:7d"
        """
        if not self.service:
            if not self.authenticate():
                return []

        try:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )

            messages = results.get("messages", [])
            emails = []

            for msg in messages:
                email = self.get_email(msg["id"], include_body=False)
                if email:
                    emails.append(email)

            return emails

        except HttpError as e:
            print(f"Error searching emails: {e}")
            return []

    def get_email(self, email_id: str, include_body: bool = True) -> Optional[Email]:
        """Get a specific email by ID."""
        if not self.service:
            if not self.authenticate():
                return None

        try:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=email_id, format="full")
                .execute()
            )

            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}

            body = None
            if include_body:
                body = self._extract_body(msg["payload"])

            return Email(
                id=msg["id"],
                thread_id=msg["threadId"],
                subject=headers.get("Subject", ""),
                sender=headers.get("From", ""),
                to=headers.get("To", ""),
                date=headers.get("Date", ""),
                snippet=msg.get("snippet", ""),
                body=body,
            )

        except HttpError as e:
            print(f"Error getting email: {e}")
            return None

    def _extract_body(self, payload: dict) -> str:
        """Extract body text from email payload."""
        if "body" in payload and payload["body"].get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")

        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    if part["body"].get("data"):
                        return base64.urlsafe_b64decode(
                            part["body"]["data"]
                        ).decode("utf-8")
                elif part["mimeType"] == "text/html":
                    if part["body"].get("data"):
                        # Return HTML if no plain text
                        return base64.urlsafe_b64decode(
                            part["body"]["data"]
                        ).decode("utf-8")
                elif "parts" in part:
                    # Nested multipart
                    body = self._extract_body(part)
                    if body:
                        return body

        return ""

    def create_draft(
        self, to: str, subject: str, body: str, reply_to_id: Optional[str] = None
    ) -> Optional[Draft]:
        """
        Create an email draft.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text)
            reply_to_id: Message ID to reply to (optional)
        """
        if not self.service:
            if not self.authenticate():
                return None

        try:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject

            if reply_to_id:
                # Get the original message for threading
                original = self.get_email(reply_to_id, include_body=False)
                if original:
                    message["In-Reply-To"] = reply_to_id
                    message["References"] = reply_to_id

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            draft_body = {"message": {"raw": raw}}
            if reply_to_id:
                original = self.get_email(reply_to_id)
                if original:
                    draft_body["message"]["threadId"] = original.thread_id

            draft = (
                self.service.users()
                .drafts()
                .create(userId="me", body=draft_body)
                .execute()
            )

            return Draft(
                id=draft["id"],
                message_id=draft["message"]["id"],
                subject=subject,
                to=to,
                body=body,
            )

        except HttpError as e:
            print(f"Error creating draft: {e}")
            return None

    def send_draft(self, draft_id: str) -> bool:
        """
        Send an existing draft.

        WARNING: This actually sends the email. Should be gated by approval.
        """
        if not self.service:
            if not self.authenticate():
                return False

        try:
            self.service.users().drafts().send(
                userId="me", body={"id": draft_id}
            ).execute()
            return True

        except HttpError as e:
            print(f"Error sending draft: {e}")
            return False

    def send_email(
        self, to: str, subject: str, body: str
    ) -> bool:
        """
        Send an email directly.

        WARNING: This actually sends the email. Should be gated by approval.
        """
        if not self.service:
            if not self.authenticate():
                return False

        try:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            self.service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            return True

        except HttpError as e:
            print(f"Error sending email: {e}")
            return False

    def list_drafts(self, max_results: int = 10) -> list[Draft]:
        """List existing drafts."""
        if not self.service:
            if not self.authenticate():
                return []

        try:
            results = (
                self.service.users()
                .drafts()
                .list(userId="me", maxResults=max_results)
                .execute()
            )

            drafts = []
            for d in results.get("drafts", []):
                draft_detail = (
                    self.service.users()
                    .drafts()
                    .get(userId="me", id=d["id"])
                    .execute()
                )

                msg = draft_detail["message"]
                headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}

                drafts.append(
                    Draft(
                        id=d["id"],
                        message_id=msg["id"],
                        subject=headers.get("Subject", ""),
                        to=headers.get("To", ""),
                        body=self._extract_body(msg["payload"]),
                    )
                )

            return drafts

        except HttpError as e:
            print(f"Error listing drafts: {e}")
            return []

    def get_profile(self) -> Optional[dict]:
        """Get the authenticated user's email profile."""
        if not self.service:
            if not self.authenticate():
                return None

        try:
            return self.service.users().getProfile(userId="me").execute()
        except HttpError as e:
            print(f"Error getting profile: {e}")
            return None
