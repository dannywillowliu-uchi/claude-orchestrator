"""Google Tasks API client with OAuth2 authentication."""

import os
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Scopes required for Google Tasks API
SCOPES = ["https://www.googleapis.com/auth/tasks"]

# Default paths
DEFAULT_CREDENTIALS_FILE = "data/credentials/credentials.json"
DEFAULT_TOKEN_FILE = "data/credentials/token.json"


class GoogleTasksClient:
    """Client for interacting with Google Tasks API."""

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
        """
        Authenticate with Google Tasks API.
        Returns True if authentication successful, False otherwise.
        """
        # Load existing token if available
        if self.token_file.exists():
            self.creds = Credentials.from_authorized_user_file(
                str(self.token_file), SCOPES
            )

        # Refresh or get new credentials if needed
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
                    print("Please download OAuth credentials from Google Cloud Console")
                    print("and save them to: data/credentials/credentials.json")
                    return False

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_file), SCOPES
                )
                self.creds = flow.run_local_server(port=0)

            # Save the credentials for next time
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_file, "w") as token:
                token.write(self.creds.to_json())

        # Build the service
        self.service = build("tasks", "v1", credentials=self.creds)
        return True

    def list_task_lists(self) -> list[dict]:
        """Get all task lists."""
        if not self.service:
            if not self.authenticate():
                return []

        try:
            results = self.service.tasklists().list(maxResults=100).execute()
            return results.get("items", [])
        except HttpError as e:
            print(f"Error listing task lists: {e}")
            return []

    def get_tasks(
        self,
        list_id: str = "@default",
        show_completed: bool = False,
        sync_token: Optional[str] = None,
    ) -> tuple[list[dict], Optional[str]]:
        """
        Get tasks from a task list.
        Returns (tasks, next_sync_token).
        """
        if not self.service:
            if not self.authenticate():
                return [], None

        try:
            params = {
                "tasklist": list_id,
                "showCompleted": show_completed,
                "showHidden": False,
                "maxResults": 100,
            }

            # Use sync token for incremental sync if available
            if sync_token:
                params["syncToken"] = sync_token

            results = self.service.tasks().list(**params).execute()
            tasks = results.get("items", [])
            next_sync_token = results.get("nextSyncToken")

            return tasks, next_sync_token

        except HttpError as e:
            # If sync token is invalid, do a full sync
            if e.resp.status == 410 and sync_token:
                print("Sync token expired, performing full sync...")
                return self.get_tasks(list_id, show_completed, None)
            print(f"Error getting tasks: {e}")
            return [], None

    def get_task(self, list_id: str, task_id: str) -> Optional[dict]:
        """Get a specific task."""
        if not self.service:
            if not self.authenticate():
                return None

        try:
            return self.service.tasks().get(tasklist=list_id, task=task_id).execute()
        except HttpError as e:
            print(f"Error getting task: {e}")
            return None

    def complete_task(self, list_id: str, task_id: str) -> bool:
        """Mark a task as completed."""
        if not self.service:
            if not self.authenticate():
                return False

        try:
            task = self.service.tasks().get(tasklist=list_id, task=task_id).execute()
            task["status"] = "completed"
            task["completed"] = datetime.utcnow().isoformat() + "Z"
            self.service.tasks().update(
                tasklist=list_id, task=task_id, body=task
            ).execute()
            return True
        except HttpError as e:
            print(f"Error completing task: {e}")
            return False

    def create_task(
        self,
        list_id: str,
        title: str,
        notes: Optional[str] = None,
        due: Optional[str] = None,
    ) -> Optional[dict]:
        """Create a new task."""
        if not self.service:
            if not self.authenticate():
                return None

        try:
            task_body = {"title": title}
            if notes:
                task_body["notes"] = notes
            if due:
                task_body["due"] = due

            return (
                self.service.tasks()
                .insert(tasklist=list_id, body=task_body)
                .execute()
            )
        except HttpError as e:
            print(f"Error creating task: {e}")
            return None

    def update_task_notes(
        self, list_id: str, task_id: str, notes: str
    ) -> Optional[dict]:
        """Update task notes."""
        if not self.service:
            if not self.authenticate():
                return None

        try:
            task = self.service.tasks().get(tasklist=list_id, task=task_id).execute()
            task["notes"] = notes
            return (
                self.service.tasks()
                .update(tasklist=list_id, task=task_id, body=task)
                .execute()
            )
        except HttpError as e:
            print(f"Error updating task: {e}")
            return None
