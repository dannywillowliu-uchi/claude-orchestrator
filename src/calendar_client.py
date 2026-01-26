"""Google Calendar API client."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# Calendar scopes
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

DEFAULT_CREDENTIALS_FILE = "data/credentials/credentials.json"
DEFAULT_TOKEN_FILE = "data/credentials/calendar_token.json"


@dataclass
class CalendarEvent:
    id: str
    summary: str
    start: str
    end: str
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[list[str]] = None
    html_link: Optional[str] = None


class CalendarClient:
    """Client for Google Calendar API operations."""

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
        """Authenticate with Google Calendar API."""
        if self.token_file.exists():
            self.creds = Credentials.from_authorized_user_file(
                str(self.token_file), CALENDAR_SCOPES
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
                    str(self.credentials_file), CALENDAR_SCOPES
                )
                self.creds = flow.run_local_server(port=0)

            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_file, "w") as token:
                token.write(self.creds.to_json())

        self.service = build("calendar", "v3", credentials=self.creds)
        return True

    def list_calendars(self) -> list[dict]:
        """List all calendars the user has access to."""
        if not self.service:
            if not self.authenticate():
                return []

        try:
            results = self.service.calendarList().list().execute()
            return [
                {"id": cal["id"], "summary": cal["summary"]}
                for cal in results.get("items", [])
            ]
        except HttpError as e:
            print(f"Error listing calendars: {e}")
            return []

    def get_upcoming_events(
        self,
        days: int = 7,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> list[CalendarEvent]:
        """
        Get upcoming events for the next N days.

        Args:
            days: Number of days to look ahead
            calendar_id: Calendar ID (default: primary)
            max_results: Maximum number of events to return
        """
        if not self.service:
            if not self.authenticate():
                return []

        try:
            now = datetime.utcnow()
            time_min = now.isoformat() + "Z"
            time_max = (now + timedelta(days=days)).isoformat() + "Z"

            results = (
                self.service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = []
            for event in results.get("items", []):
                start = event["start"].get("dateTime", event["start"].get("date"))
                end = event["end"].get("dateTime", event["end"].get("date"))

                attendees = None
                if "attendees" in event:
                    attendees = [a.get("email") for a in event["attendees"]]

                events.append(
                    CalendarEvent(
                        id=event["id"],
                        summary=event.get("summary", "No title"),
                        start=start,
                        end=end,
                        description=event.get("description"),
                        location=event.get("location"),
                        attendees=attendees,
                        html_link=event.get("htmlLink"),
                    )
                )

            return events

        except HttpError as e:
            print(f"Error getting events: {e}")
            return []

    def get_events_on_date(
        self, date: datetime, calendar_id: str = "primary"
    ) -> list[CalendarEvent]:
        """Get all events on a specific date."""
        if not self.service:
            if not self.authenticate():
                return []

        try:
            start_of_day = datetime(date.year, date.month, date.day)
            end_of_day = start_of_day + timedelta(days=1)

            time_min = start_of_day.isoformat() + "Z"
            time_max = end_of_day.isoformat() + "Z"

            results = (
                self.service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = []
            for event in results.get("items", []):
                start = event["start"].get("dateTime", event["start"].get("date"))
                end = event["end"].get("dateTime", event["end"].get("date"))

                events.append(
                    CalendarEvent(
                        id=event["id"],
                        summary=event.get("summary", "No title"),
                        start=start,
                        end=end,
                        description=event.get("description"),
                        location=event.get("location"),
                    )
                )

            return events

        except HttpError as e:
            print(f"Error getting events: {e}")
            return []

    def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[list[str]] = None,
        calendar_id: str = "primary",
        recurrence: Optional[str] = None,
        recurrence_count: Optional[int] = None,
        recurrence_until: Optional[datetime] = None,
    ) -> Optional[CalendarEvent]:
        """
        Create a new calendar event with optional recurrence.

        Args:
            summary: Event title
            start: Start datetime
            end: End datetime
            description: Event description (optional)
            location: Event location (optional)
            attendees: List of attendee emails (optional)
            calendar_id: Calendar to add event to
            recurrence: Recurrence frequency - "daily", "weekly", "monthly", "yearly" (optional)
            recurrence_count: Number of occurrences (optional, use with recurrence)
            recurrence_until: End date for recurrence (optional, use with recurrence)
        """
        if not self.service:
            if not self.authenticate():
                return None

        try:
            event_body = {
                "summary": summary,
                "start": {"dateTime": start.isoformat(), "timeZone": "America/Chicago"},
                "end": {"dateTime": end.isoformat(), "timeZone": "America/Chicago"},
            }

            if description:
                event_body["description"] = description
            if location:
                event_body["location"] = location
            if attendees:
                event_body["attendees"] = [{"email": email} for email in attendees]

            # Add recurrence rule if specified
            if recurrence:
                rrule = self._build_recurrence_rule(
                    recurrence, recurrence_count, recurrence_until
                )
                if rrule:
                    event_body["recurrence"] = [rrule]

            event = (
                self.service.events()
                .insert(calendarId=calendar_id, body=event_body)
                .execute()
            )

            return CalendarEvent(
                id=event["id"],
                summary=event["summary"],
                start=event["start"]["dateTime"],
                end=event["end"]["dateTime"],
                description=event.get("description"),
                location=event.get("location"),
                html_link=event.get("htmlLink"),
            )

        except HttpError as e:
            print(f"Error creating event: {e}")
            return None

    def _build_recurrence_rule(
        self,
        frequency: str,
        count: Optional[int] = None,
        until: Optional[datetime] = None,
    ) -> Optional[str]:
        """
        Build an RFC 5545 RRULE string for recurring events.

        Args:
            frequency: "daily", "weekly", "monthly", "yearly"
            count: Number of occurrences
            until: End date for recurrence

        Returns:
            RRULE string like "RRULE:FREQ=WEEKLY;COUNT=10"
        """
        freq_map = {
            "daily": "DAILY",
            "weekly": "WEEKLY",
            "monthly": "MONTHLY",
            "yearly": "YEARLY",
        }

        freq = freq_map.get(frequency.lower())
        if not freq:
            return None

        rule_parts = [f"RRULE:FREQ={freq}"]

        if count:
            rule_parts.append(f"COUNT={count}")
        elif until:
            # Format: YYYYMMDDTHHMMSSZ
            until_str = until.strftime("%Y%m%dT%H%M%SZ")
            rule_parts.append(f"UNTIL={until_str}")

        return ";".join(rule_parts)

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """Delete a calendar event."""
        if not self.service:
            if not self.authenticate():
                return False

        try:
            self.service.events().delete(
                calendarId=calendar_id, eventId=event_id
            ).execute()
            return True
        except HttpError as e:
            print(f"Error deleting event: {e}")
            return False

    def find_free_slots(
        self,
        duration_minutes: int,
        days_ahead: int = 7,
        working_hours: tuple[int, int] = (9, 17),
        calendar_id: str = "primary",
    ) -> list[tuple[datetime, datetime]]:
        """
        Find free time slots in the calendar.

        Args:
            duration_minutes: Required slot duration
            days_ahead: How many days to look ahead
            working_hours: Tuple of (start_hour, end_hour) in 24h format
            calendar_id: Calendar to check

        Returns:
            List of (start, end) datetime tuples for available slots
        """
        events = self.get_upcoming_events(days=days_ahead, calendar_id=calendar_id)

        # Build busy times
        busy_times = []
        for event in events:
            try:
                start = datetime.fromisoformat(event.start.replace("Z", "+00:00"))
                end = datetime.fromisoformat(event.end.replace("Z", "+00:00"))
                busy_times.append((start, end))
            except (ValueError, AttributeError):
                continue

        # Find free slots
        free_slots = []
        current = datetime.now()

        for day_offset in range(days_ahead):
            day = current + timedelta(days=day_offset)
            day_start = day.replace(
                hour=working_hours[0], minute=0, second=0, microsecond=0
            )
            day_end = day.replace(
                hour=working_hours[1], minute=0, second=0, microsecond=0
            )

            if day_start < current:
                day_start = current

            slot_start = day_start
            while slot_start + timedelta(minutes=duration_minutes) <= day_end:
                slot_end = slot_start + timedelta(minutes=duration_minutes)

                # Check if slot conflicts with any busy time
                is_free = True
                for busy_start, busy_end in busy_times:
                    if not (slot_end <= busy_start or slot_start >= busy_end):
                        is_free = False
                        slot_start = busy_end
                        break

                if is_free:
                    free_slots.append((slot_start, slot_end))
                    slot_start = slot_end
                    if len(free_slots) >= 10:  # Limit results
                        return free_slots

        return free_slots
