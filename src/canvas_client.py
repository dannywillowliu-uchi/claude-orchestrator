"""Canvas LMS Client for UChicago integration."""

import os
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from pathlib import Path

from canvasapi import Canvas
from canvasapi.course import Course
from canvasapi.assignment import Assignment
from canvasapi.submission import Submission


@dataclass
class CanvasAssignment:
    """Structured assignment data."""
    id: int
    name: str
    course_name: str
    course_id: int
    due_at: Optional[str]
    points_possible: float
    description: Optional[str]
    submission_types: list[str]
    is_submitted: bool = False
    score: Optional[float] = None
    grade: Optional[str] = None


@dataclass
class CanvasCourse:
    """Structured course data."""
    id: int
    name: str
    code: str
    term: Optional[str] = None
    enrollment_type: str = "student"


@dataclass
class CanvasAnnouncement:
    """Structured announcement data."""
    id: int
    title: str
    message: str
    course_name: str
    posted_at: str
    author: str


class CanvasClient:
    """Client for UChicago Canvas LMS API."""

    CANVAS_URL = "https://canvas.uchicago.edu"
    TOKEN_FILE = "data/credentials/canvas_token.txt"

    def __init__(self, api_token: Optional[str] = None, token_file: str = TOKEN_FILE):
        self.token_file = Path(token_file)
        self._api_token = api_token
        self._canvas: Optional[Canvas] = None

    @property
    def api_token(self) -> Optional[str]:
        """Get API token from file or environment."""
        if self._api_token:
            return self._api_token

        # Try environment variable
        token = os.getenv("CANVAS_API_TOKEN")
        if token:
            return token

        # Try token file
        if self.token_file.exists():
            return self.token_file.read_text().strip()

        return None

    def save_token(self, token: str):
        """Save API token to file."""
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(token)
        self._api_token = token
        self._canvas = None  # Reset connection

    def is_configured(self) -> bool:
        """Check if Canvas is configured with an API token."""
        return self.api_token is not None

    def _get_canvas(self) -> Canvas:
        """Get or create Canvas API instance."""
        if self._canvas is None:
            token = self.api_token
            if not token:
                raise ValueError(
                    "Canvas API token not configured. "
                    "Generate one at canvas.uchicago.edu -> Account -> Settings -> New Access Token"
                )
            self._canvas = Canvas(self.CANVAS_URL, token)
        return self._canvas

    def get_current_user(self) -> dict:
        """Get current user info (useful for testing connection)."""
        canvas = self._get_canvas()
        user = canvas.get_current_user()
        return {
            "id": user.id,
            "name": user.name,
            "email": getattr(user, "email", None),
        }

    def get_courses(self, include_past: bool = False) -> list[CanvasCourse]:
        """Get user's courses."""
        canvas = self._get_canvas()

        # Get courses with enrollments
        if include_past:
            courses = canvas.get_courses(include=["term", "total_scores"])
        else:
            courses = canvas.get_courses(
                enrollment_state="active",
                include=["term", "total_scores"]
            )

        result = []
        for course in courses:
            try:
                term_name = None
                if hasattr(course, "term") and course.term:
                    term_name = course.term.get("name")

                result.append(CanvasCourse(
                    id=course.id,
                    name=course.name,
                    code=getattr(course, "course_code", ""),
                    term=term_name,
                ))
            except Exception:
                # Skip courses that can't be accessed
                continue

        return result

    def get_course(self, course_id: int) -> Optional[Course]:
        """Get a specific course."""
        canvas = self._get_canvas()
        try:
            return canvas.get_course(course_id)
        except Exception:
            return None

    def get_assignments(
        self,
        course_id: Optional[int] = None,
        upcoming_only: bool = True,
        days_ahead: int = 14,
    ) -> list[CanvasAssignment]:
        """
        Get assignments, optionally filtered by course.

        Args:
            course_id: Specific course ID, or None for all courses
            upcoming_only: Only show assignments due in the future
            days_ahead: Number of days ahead to look for upcoming assignments
        """
        canvas = self._get_canvas()
        assignments = []

        # Get courses to query
        if course_id:
            courses = [canvas.get_course(course_id)]
        else:
            courses = canvas.get_courses(enrollment_state="active")

        cutoff_date = datetime.now() + timedelta(days=days_ahead)

        for course in courses:
            try:
                course_name = course.name
                for assignment in course.get_assignments(order_by="due_at"):
                    try:
                        due_at = getattr(assignment, "due_at", None)

                        # Filter by date if upcoming_only
                        if upcoming_only and due_at:
                            due_date = datetime.fromisoformat(
                                due_at.replace("Z", "+00:00")
                            )
                            if due_date.replace(tzinfo=None) < datetime.now():
                                continue
                            if due_date.replace(tzinfo=None) > cutoff_date:
                                continue

                        # Check submission status
                        is_submitted = False
                        score = None
                        grade = None
                        try:
                            submission = assignment.get_submission("self")
                            is_submitted = submission.workflow_state == "submitted" or submission.submitted_at is not None
                            score = getattr(submission, "score", None)
                            grade = getattr(submission, "grade", None)
                        except Exception:
                            pass

                        assignments.append(CanvasAssignment(
                            id=assignment.id,
                            name=assignment.name,
                            course_name=course_name,
                            course_id=course.id,
                            due_at=due_at,
                            points_possible=getattr(assignment, "points_possible", 0) or 0,
                            description=getattr(assignment, "description", None),
                            submission_types=getattr(assignment, "submission_types", []),
                            is_submitted=is_submitted,
                            score=score,
                            grade=grade,
                        ))
                    except Exception:
                        continue
            except Exception:
                continue

        # Sort by due date
        assignments.sort(key=lambda a: a.due_at or "9999")
        return assignments

    def get_upcoming_deadlines(self, days: int = 7) -> list[CanvasAssignment]:
        """Get assignments due in the next N days."""
        return self.get_assignments(upcoming_only=True, days_ahead=days)

    def get_announcements(
        self,
        course_id: Optional[int] = None,
        days_back: int = 7,
    ) -> list[CanvasAnnouncement]:
        """Get recent announcements."""
        canvas = self._get_canvas()
        announcements = []

        # Get courses
        if course_id:
            courses = [canvas.get_course(course_id)]
        else:
            courses = list(canvas.get_courses(enrollment_state="active"))

        # Canvas API requires context_codes for announcements
        context_codes = [f"course_{c.id}" for c in courses]

        if not context_codes:
            return []

        start_date = datetime.now() - timedelta(days=days_back)

        try:
            # Get announcements via the user's announcements endpoint
            for course in courses:
                try:
                    disc_topics = course.get_discussion_topics(only_announcements=True)
                    for topic in disc_topics:
                        posted_at = getattr(topic, "posted_at", None)
                        if posted_at:
                            post_date = datetime.fromisoformat(
                                posted_at.replace("Z", "+00:00")
                            )
                            if post_date.replace(tzinfo=None) < start_date:
                                continue

                        author_name = "Unknown"
                        if hasattr(topic, "author") and topic.author:
                            author_name = topic.author.get("display_name", "Unknown")

                        announcements.append(CanvasAnnouncement(
                            id=topic.id,
                            title=topic.title,
                            message=getattr(topic, "message", ""),
                            course_name=course.name,
                            posted_at=posted_at or "",
                            author=author_name,
                        ))
                except Exception:
                    continue
        except Exception:
            pass

        # Sort by date (newest first)
        announcements.sort(key=lambda a: a.posted_at or "", reverse=True)
        return announcements

    def get_grades(self, course_id: Optional[int] = None) -> list[dict]:
        """Get grades for courses."""
        canvas = self._get_canvas()
        grades = []

        if course_id:
            courses = [canvas.get_course(course_id, include=["total_scores"])]
        else:
            courses = canvas.get_courses(
                enrollment_state="active",
                include=["total_scores"]
            )

        for course in courses:
            try:
                # Get enrollment to access grades
                enrollments = course.get_enrollments(user_id="self")
                for enrollment in enrollments:
                    if enrollment.type == "StudentEnrollment":
                        grades.append({
                            "course_id": course.id,
                            "course_name": course.name,
                            "current_score": getattr(enrollment, "computed_current_score", None),
                            "current_grade": getattr(enrollment, "computed_current_grade", None),
                            "final_score": getattr(enrollment, "computed_final_score", None),
                            "final_grade": getattr(enrollment, "computed_final_grade", None),
                        })
                        break
            except Exception:
                continue

        return grades

    def get_course_modules(self, course_id: int) -> list[dict]:
        """Get modules for a course."""
        canvas = self._get_canvas()
        course = canvas.get_course(course_id)
        modules = []

        try:
            for module in course.get_modules():
                items = []
                try:
                    for item in module.get_module_items():
                        items.append({
                            "id": item.id,
                            "title": item.title,
                            "type": item.type,
                            "url": getattr(item, "html_url", None),
                        })
                except Exception:
                    pass

                modules.append({
                    "id": module.id,
                    "name": module.name,
                    "position": module.position,
                    "items_count": len(items),
                    "items": items[:10],  # Limit items
                })
        except Exception:
            pass

        return modules

    def get_todo_items(self) -> list[dict]:
        """Get user's Canvas todo items."""
        canvas = self._get_canvas()
        user = canvas.get_current_user()
        todos = []

        try:
            for item in user.get_todo_items():
                todos.append({
                    "type": item.type,
                    "assignment_id": getattr(item, "assignment", {}).get("id"),
                    "assignment_name": getattr(item, "assignment", {}).get("name"),
                    "course_id": getattr(item, "course_id", None),
                    "due_at": getattr(item, "assignment", {}).get("due_at"),
                    "html_url": getattr(item, "html_url", None),
                })
        except Exception:
            pass

        return todos
