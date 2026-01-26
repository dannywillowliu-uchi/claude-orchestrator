"""Canvas Browser Automation Client using Playwright.

Handles UChicago SSO + Duo 2FA authentication and scrapes Canvas pages
when the API is disabled.
"""

import os
import asyncio
import logging
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .security import (
    validate_save_path,
    sanitize_filename,
    rate_limiter,
    secure_storage,
)

logger = logging.getLogger(__name__)


@dataclass
class CanvasAssignment:
    """Assignment data scraped from Canvas."""
    name: str
    course: str
    due_date: Optional[str]
    points: Optional[str]
    status: str  # 'submitted', 'missing', 'upcoming', 'not_submitted'
    url: str


@dataclass
class CanvasAnnouncement:
    """Announcement data scraped from Canvas."""
    title: str
    course: str
    date: str
    preview: str
    url: str


@dataclass
class CanvasCourse:
    """Course data scraped from Canvas."""
    name: str
    code: str
    url: str
    course_id: Optional[str] = None
    term: Optional[str] = None


@dataclass
class CanvasFile:
    """File data from Canvas."""
    name: str
    url: str
    file_type: str  # 'file', 'folder'
    size: Optional[str] = None
    modified: Optional[str] = None


@dataclass
class CanvasDiscussion:
    """Discussion topic data."""
    title: str
    author: str
    date: str
    replies: int
    unread: bool
    url: str


@dataclass
class CanvasModule:
    """Module data from Canvas."""
    name: str
    items: list[dict]  # list of module items
    status: str  # 'completed', 'in_progress', 'locked'


@dataclass
class CanvasMessage:
    """Inbox message data."""
    subject: str
    sender: str
    date: str
    preview: str
    url: str
    unread: bool


@dataclass
class CanvasAssignmentDetails:
    """Detailed assignment data from individual assignment page."""
    name: str
    course: str
    url: str
    description: str
    due_date: Optional[str] = None
    points: Optional[str] = None
    submission_types: Optional[list[str]] = None
    available_from: Optional[str] = None
    available_until: Optional[str] = None
    attempts_allowed: Optional[str] = None
    grading_type: Optional[str] = None
    rubric: Optional[list[dict]] = None


class CanvasBrowser:
    """
    Canvas browser automation client.

    Uses Playwright to automate browser access to Canvas when the API is disabled.
    Handles UChicago SSO and Duo 2FA authentication with persistent sessions.
    Session data is stored securely using macOS Keychain when available.
    """

    CANVAS_URL = "https://canvas.uchicago.edu"
    LOGIN_URL = f"{CANVAS_URL}/login/saml"
    DASHBOARD_URL = f"{CANVAS_URL}/"

    # Session storage
    SESSION_DIR = "data/browser_sessions"
    SESSION_FILE = "canvas_session.json"
    SESSION_KEY = "canvas_browser_session"

    def __init__(self, headless: bool = True, session_dir: str = SESSION_DIR, use_secure_storage: bool = True):
        self.headless = headless
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.use_secure_storage = use_secure_storage

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._logged_in = False

    @property
    def session_file(self) -> Path:
        return self.session_dir / self.SESSION_FILE

    def _load_session_data(self) -> Optional[dict]:
        """Load session data from secure storage or file."""
        # Try secure storage first
        if self.use_secure_storage:
            session_json = secure_storage.retrieve(self.SESSION_KEY)
            if session_json:
                try:
                    logger.info("Loaded session from secure storage")
                    return json.loads(session_json)
                except json.JSONDecodeError:
                    logger.warning("Invalid session data in secure storage")

        # Fall back to file
        if self.session_file.exists():
            try:
                with open(self.session_file, "r") as f:
                    logger.info("Loaded session from file")
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load session file: {e}")

        return None

    def _save_session_data(self, session_data: dict):
        """Save session data to secure storage and file."""
        session_json = json.dumps(session_data)

        # Save to secure storage
        if self.use_secure_storage:
            if secure_storage.store(self.SESSION_KEY, session_json):
                logger.info("Saved session to secure storage")
            else:
                logger.warning("Could not save to secure storage, using file only")

        # Always save to file as backup (with restricted permissions)
        try:
            with open(self.session_file, "w") as f:
                json.dump(session_data, f)
            os.chmod(self.session_file, 0o600)
            logger.info("Saved session to file")
        except IOError as e:
            logger.warning(f"Could not save session file: {e}")

    async def start(self):
        """Start the browser."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)

            # Load existing session if available
            session_data = self._load_session_data()
            if session_data:
                try:
                    self._context = await self._browser.new_context(
                        storage_state=session_data
                    )
                    logger.info("Restored browser session")
                except Exception as e:
                    logger.warning(f"Could not restore session: {e}")
                    self._context = await self._browser.new_context()
            else:
                self._context = await self._browser.new_context()

            self._page = await self._context.new_page()

    async def stop(self):
        """Stop the browser and save session."""
        if self._context:
            # Save session for next time
            try:
                session_data = await self._context.storage_state()
                self._save_session_data(session_data)
            except Exception as e:
                logger.warning(f"Could not save session: {e}")

            await self._context.close()

        if self._browser:
            await self._browser.close()

        if self._playwright:
            await self._playwright.stop()

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False

    async def is_logged_in(self) -> bool:
        """Check if we're logged into Canvas."""
        if not self._page:
            return False

        try:
            await self._page.goto(self.DASHBOARD_URL, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(2)  # Wait for any redirects

            # Check if we're on the dashboard (not redirected to login)
            current_url = self._page.url

            # If we're still on canvas.uchicago.edu and not on login page, we're logged in
            if "canvas.uchicago.edu" in current_url and "login" not in current_url and "shibboleth" not in current_url.lower():
                self._logged_in = True
                return True

            return False
        except Exception as e:
            logger.warning(f"Error checking login status: {e}")
            return False

    async def login(self, timeout: int = 120) -> bool:
        """
        Login to Canvas via UChicago SSO + Duo.

        This will:
        1. Navigate to Canvas login
        2. Redirect to UChicago Shibboleth SSO
        3. Wait for you to enter credentials and approve Duo push
        4. Save session for future use

        Args:
            timeout: Seconds to wait for login completion (default: 120)

        Returns:
            True if login successful
        """
        if not self._page:
            await self.start()

        # Check if already logged in
        if await self.is_logged_in():
            logger.info("Already logged in to Canvas")
            return True

        logger.info("Starting Canvas login flow...")
        logger.info("Please complete login in the browser window (including Duo 2FA)")

        # Navigate to login with longer timeout for SAML redirect
        try:
            await self._page.goto(self.LOGIN_URL, timeout=60000, wait_until="domcontentloaded")
        except Exception as e:
            logger.warning(f"Initial navigation had issue (may be redirect): {e}")
            # Continue anyway - we'll poll for the dashboard

        # Wait for user to complete login (poll for dashboard)
        start_time = datetime.now()
        while (datetime.now() - start_time).seconds < timeout:
            await asyncio.sleep(2)

            try:
                current_url = self._page.url

                # Check if we've reached the dashboard
                if "canvas.uchicago.edu" in current_url and "login" not in current_url and "shibboleth" not in current_url.lower():
                    logger.info("Login successful!")
                    self._logged_in = True

                    # Save session
                    await self._context.storage_state(path=str(self.session_file))
                    return True
            except Exception:
                continue  # Keep polling

        logger.error("Login timed out")
        return False

    async def login_interactive(self) -> bool:
        """
        Login with a visible browser window for manual authentication.

        Opens a non-headless browser so you can see and interact with:
        - UChicago SSO login page
        - Duo 2FA prompt
        """
        # Restart with visible browser
        await self.stop()
        self.headless = False
        await self.start()

        result = await self.login(timeout=180)  # 3 minutes for manual login

        # Switch back to headless for future operations
        self.headless = True

        return result

    async def _ensure_logged_in(self):
        """Ensure we're logged in before operations."""
        if not self._logged_in:
            if not await self.is_logged_in():
                raise RuntimeError(
                    "Not logged in to Canvas. Call login() or login_interactive() first."
                )

    async def get_courses(self) -> list[CanvasCourse]:
        """Get list of current courses."""
        await self._ensure_logged_in()

        courses = []

        # Go to courses page
        await self._page.goto(f"{self.CANVAS_URL}/courses")
        await self._page.wait_for_load_state("networkidle")

        # Find course cards/links
        course_elements = await self._page.query_selector_all("a.ic-DashboardCard__link, tr.course-list-table-row a")

        for elem in course_elements:
            try:
                name = await elem.inner_text()
                url = await elem.get_attribute("href")

                if url and name.strip():
                    courses.append(CanvasCourse(
                        name=name.strip(),
                        code="",
                        url=url if url.startswith("http") else f"{self.CANVAS_URL}{url}",
                    ))
            except Exception:
                continue

        # Also try the course list format
        if not courses:
            rows = await self._page.query_selector_all("table tbody tr")
            for row in rows:
                try:
                    link = await row.query_selector("a")
                    if link:
                        name = await link.inner_text()
                        url = await link.get_attribute("href")
                        if name.strip():
                            courses.append(CanvasCourse(
                                name=name.strip(),
                                code="",
                                url=url if url.startswith("http") else f"{self.CANVAS_URL}{url}",
                            ))
                except Exception:
                    continue

        return courses

    async def get_assignments(self, upcoming_only: bool = True) -> list[CanvasAssignment]:
        """
        Get assignments from Canvas.

        Args:
            upcoming_only: Only return upcoming/todo assignments
        """
        await self._ensure_logged_in()

        assignments = []

        # Go to the todo/assignments page
        if upcoming_only:
            await self._page.goto(f"{self.CANVAS_URL}/?todo=1")
        else:
            await self._page.goto(f"{self.CANVAS_URL}/calendar")

        await self._page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)  # Extra wait for dynamic content

        # Try to find todo items on dashboard
        todo_items = await self._page.query_selector_all(".to-do-list li, .planner-item, [class*='todo'], [class*='assignment']")

        for item in todo_items:
            try:
                # Try various selectors for assignment info
                name_elem = await item.query_selector("a, .title, [class*='title']")
                course_elem = await item.query_selector("[class*='course'], .context, small")
                due_elem = await item.query_selector("[class*='due'], time, [class*='date']")

                name = await name_elem.inner_text() if name_elem else ""
                course = await course_elem.inner_text() if course_elem else ""
                due = await due_elem.inner_text() if due_elem else ""

                link = await item.query_selector("a")
                url = await link.get_attribute("href") if link else ""

                if name.strip():
                    assignments.append(CanvasAssignment(
                        name=name.strip(),
                        course=course.strip(),
                        due_date=due.strip(),
                        points=None,
                        status="upcoming",
                        url=url if url.startswith("http") else f"{self.CANVAS_URL}{url}" if url else "",
                    ))
            except Exception:
                continue

        return assignments

    async def get_announcements(self, limit: int = 10) -> list[CanvasAnnouncement]:
        """Get recent announcements."""
        await self._ensure_logged_in()

        announcements = []

        # Go to dashboard with announcements
        await self._page.goto(self.DASHBOARD_URL)
        await self._page.wait_for_load_state("networkidle")

        # Find announcement elements
        ann_items = await self._page.query_selector_all("[class*='announcement'], .ic-announcement-row, .stream-announcement")

        for item in ann_items[:limit]:
            try:
                title_elem = await item.query_selector("a, h3, [class*='title']")
                course_elem = await item.query_selector("[class*='course'], .context")
                date_elem = await item.query_selector("time, [class*='date']")
                preview_elem = await item.query_selector("p, [class*='message'], [class*='body']")

                title = await title_elem.inner_text() if title_elem else ""
                course = await course_elem.inner_text() if course_elem else ""
                date = await date_elem.inner_text() if date_elem else ""
                preview = await preview_elem.inner_text() if preview_elem else ""

                link = await item.query_selector("a")
                url = await link.get_attribute("href") if link else ""

                if title.strip():
                    announcements.append(CanvasAnnouncement(
                        title=title.strip(),
                        course=course.strip(),
                        date=date.strip(),
                        preview=preview.strip()[:200],
                        url=url if url.startswith("http") else f"{self.CANVAS_URL}{url}" if url else "",
                    ))
            except Exception:
                continue

        return announcements

    async def get_grades(self) -> list[dict]:
        """Get grades from Canvas."""
        await self._ensure_logged_in()

        grades = []

        # Go to grades page
        await self._page.goto(f"{self.CANVAS_URL}/grades")
        await self._page.wait_for_load_state("networkidle")

        # Find grade rows
        rows = await self._page.query_selector_all("tr.course, .student_grades tr, [class*='grade-row']")

        for row in rows:
            try:
                course_elem = await row.query_selector("a, .course, [class*='name']")
                grade_elem = await row.query_selector(".percent, .grade, [class*='score']")

                course = await course_elem.inner_text() if course_elem else ""
                grade = await grade_elem.inner_text() if grade_elem else ""

                if course.strip():
                    grades.append({
                        "course": course.strip(),
                        "grade": grade.strip(),
                    })
            except Exception:
                continue

        return grades

    async def get_calendar_events(self, days_ahead: int = 7) -> list[dict]:
        """Get calendar events."""
        await self._ensure_logged_in()

        events = []

        # Go to calendar
        await self._page.goto(f"{self.CANVAS_URL}/calendar")
        await self._page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        # Find calendar events
        event_elems = await self._page.query_selector_all(".fc-event, [class*='calendar-event'], .agenda-event")

        for elem in event_elems:
            try:
                title = await elem.inner_text()
                url = await elem.get_attribute("href") or ""

                if title.strip():
                    events.append({
                        "title": title.strip(),
                        "url": url if url.startswith("http") else f"{self.CANVAS_URL}{url}" if url else "",
                    })
            except Exception:
                continue

        return events

    async def get_course_files(self, course_url: str) -> list[CanvasFile]:
        """
        Get files from a specific course.

        Args:
            course_url: The course URL (e.g., https://canvas.uchicago.edu/courses/12345)
        """
        await self._ensure_logged_in()

        files = []

        # Navigate to course files
        if "/courses/" in course_url:
            files_url = f"{course_url}/files"
        else:
            files_url = course_url

        await self._page.goto(files_url)
        await self._page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        # Find file/folder items
        file_items = await self._page.query_selector_all(
            ".ef-item-row, [class*='file'], [class*='folder'], tr[class*='file'], tr[class*='folder']"
        )

        for item in file_items:
            try:
                name_elem = await item.query_selector("a, .ef-name-col, [class*='name']")
                size_elem = await item.query_selector("[class*='size'], .ef-size-col")
                date_elem = await item.query_selector("[class*='date'], .ef-date-modified-col, time")

                name = await name_elem.inner_text() if name_elem else ""
                size = await size_elem.inner_text() if size_elem else ""
                date = await date_elem.inner_text() if date_elem else ""

                link = await item.query_selector("a")
                url = await link.get_attribute("href") if link else ""

                # Determine if folder or file
                is_folder = await item.query_selector("[class*='folder'], .icon-folder")
                file_type = "folder" if is_folder else "file"

                if name.strip():
                    files.append(CanvasFile(
                        name=name.strip(),
                        url=url if url.startswith("http") else f"{self.CANVAS_URL}{url}" if url else "",
                        file_type=file_type,
                        size=size.strip() if size else None,
                        modified=date.strip() if date else None,
                    ))
            except Exception:
                continue

        return files

    async def get_course_discussions(self, course_url: str) -> list[CanvasDiscussion]:
        """
        Get discussions from a specific course.

        Args:
            course_url: The course URL
        """
        await self._ensure_logged_in()

        discussions = []

        # Navigate to course discussions
        if "/courses/" in course_url:
            disc_url = f"{course_url}/discussion_topics"
        else:
            disc_url = course_url

        await self._page.goto(disc_url)
        await self._page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        # Find discussion items
        disc_items = await self._page.query_selector_all(
            ".discussion, .discussionTopicIndexList__item, [class*='discussion-row'], tr.discussion-topic"
        )

        for item in disc_items:
            try:
                title_elem = await item.query_selector("a.discussion-title, [class*='title'] a, a")
                author_elem = await item.query_selector("[class*='author'], .user_name, .author")
                date_elem = await item.query_selector("[class*='date'], time, .timestamp")
                replies_elem = await item.query_selector("[class*='replies'], [class*='count'], .discussion-unread-indicator")

                title = await title_elem.inner_text() if title_elem else ""
                author = await author_elem.inner_text() if author_elem else ""
                date = await date_elem.inner_text() if date_elem else ""
                replies_text = await replies_elem.inner_text() if replies_elem else "0"

                link = await item.query_selector("a")
                url = await link.get_attribute("href") if link else ""

                # Check for unread indicator
                unread_elem = await item.query_selector(".unread, [class*='unread']")
                unread = unread_elem is not None

                # Parse replies count
                try:
                    replies = int(''.join(filter(str.isdigit, replies_text)) or '0')
                except ValueError:
                    replies = 0

                if title.strip():
                    discussions.append(CanvasDiscussion(
                        title=title.strip(),
                        author=author.strip(),
                        date=date.strip(),
                        replies=replies,
                        unread=unread,
                        url=url if url.startswith("http") else f"{self.CANVAS_URL}{url}" if url else "",
                    ))
            except Exception:
                continue

        return discussions

    async def get_course_modules(self, course_url: str) -> list[CanvasModule]:
        """
        Get modules from a specific course.

        Args:
            course_url: The course URL
        """
        await self._ensure_logged_in()

        modules = []

        # Navigate to course modules
        if "/courses/" in course_url:
            modules_url = f"{course_url}/modules"
        else:
            modules_url = course_url

        await self._page.goto(modules_url)
        await self._page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        # Find module containers
        module_elems = await self._page.query_selector_all(
            ".context_module, [class*='module'], .ig-list"
        )

        for module_elem in module_elems:
            try:
                # Get module name
                name_elem = await module_elem.query_selector(
                    ".ig-header-title, [class*='module-title'], .name, h2"
                )
                name = await name_elem.inner_text() if name_elem else ""

                # Get module items
                items = []
                item_elems = await module_elem.query_selector_all(
                    ".ig-row, .context_module_item, [class*='module-item']"
                )

                for item_elem in item_elems:
                    try:
                        item_title_elem = await item_elem.query_selector("a, .ig-title, [class*='title']")
                        item_type_elem = await item_elem.query_selector("[class*='type'], .type_icon")

                        item_title = await item_title_elem.inner_text() if item_title_elem else ""
                        item_type = await item_type_elem.get_attribute("title") if item_type_elem else "item"

                        item_link = await item_elem.query_selector("a")
                        item_url = await item_link.get_attribute("href") if item_link else ""

                        if item_title.strip():
                            items.append({
                                "title": item_title.strip(),
                                "type": item_type or "item",
                                "url": item_url if item_url.startswith("http") else f"{self.CANVAS_URL}{item_url}" if item_url else "",
                            })
                    except Exception:
                        continue

                # Check module status
                status_elem = await module_elem.query_selector("[class*='status'], .completion-status")
                status = "in_progress"
                if status_elem:
                    status_text = await status_elem.inner_text()
                    if "complete" in status_text.lower():
                        status = "completed"
                    elif "locked" in status_text.lower():
                        status = "locked"

                if name.strip():
                    modules.append(CanvasModule(
                        name=name.strip(),
                        items=items,
                        status=status,
                    ))
            except Exception:
                continue

        return modules

    async def get_course_syllabus(self, course_url: str) -> dict:
        """
        Get syllabus from a specific course.

        Args:
            course_url: The course URL
        """
        await self._ensure_logged_in()

        # Navigate to syllabus
        if "/courses/" in course_url:
            syllabus_url = f"{course_url}/assignments/syllabus"
        else:
            syllabus_url = course_url

        await self._page.goto(syllabus_url)
        await self._page.wait_for_load_state("networkidle")

        # Get syllabus content
        syllabus_elem = await self._page.query_selector(
            "#course_syllabus, .syllabus, [class*='syllabus-content'], .user_content"
        )

        content = ""
        if syllabus_elem:
            content = await syllabus_elem.inner_text()

        return {
            "url": syllabus_url,
            "content": content.strip()[:5000],  # Limit content size
        }

    async def get_inbox(self, unread_only: bool = False) -> list[CanvasMessage]:
        """
        Get inbox messages.

        Args:
            unread_only: Only show unread messages
        """
        await self._ensure_logged_in()

        messages = []

        # Navigate to inbox
        inbox_url = f"{self.CANVAS_URL}/conversations"
        if unread_only:
            inbox_url += "#filter=type=inbox&scope=unread"

        await self._page.goto(inbox_url)
        await self._page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        # Find message items
        msg_items = await self._page.query_selector_all(
            ".messages li, .conversation, [class*='message-item'], [class*='conversation']"
        )

        for item in msg_items:
            try:
                subject_elem = await item.query_selector("[class*='subject'], .subject, strong")
                sender_elem = await item.query_selector("[class*='author'], .author, .participants")
                date_elem = await item.query_selector("[class*='date'], time, .timestamp")
                preview_elem = await item.query_selector("[class*='summary'], .last-message, p")

                subject = await subject_elem.inner_text() if subject_elem else ""
                sender = await sender_elem.inner_text() if sender_elem else ""
                date = await date_elem.inner_text() if date_elem else ""
                preview = await preview_elem.inner_text() if preview_elem else ""

                link = await item.query_selector("a")
                url = await link.get_attribute("href") if link else ""

                # Check for unread
                unread = await item.query_selector(".unread, [class*='unread']") is not None

                if subject.strip() or sender.strip():
                    messages.append(CanvasMessage(
                        subject=subject.strip() or "(No Subject)",
                        sender=sender.strip(),
                        date=date.strip(),
                        preview=preview.strip()[:200],
                        url=url if url.startswith("http") else f"{self.CANVAS_URL}{url}" if url else "",
                        unread=unread,
                    ))
            except Exception:
                continue

        return messages

    async def get_course_pages(self, course_url: str) -> list[dict]:
        """
        Get wiki/pages from a specific course.

        Args:
            course_url: The course URL
        """
        await self._ensure_logged_in()

        pages = []

        # Navigate to course pages
        if "/courses/" in course_url:
            pages_url = f"{course_url}/pages"
        else:
            pages_url = course_url

        await self._page.goto(pages_url)
        await self._page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        # Find page items
        page_items = await self._page.query_selector_all(
            ".wiki-page-link, [class*='page-row'], tr.page, .page"
        )

        for item in page_items:
            try:
                title_elem = await item.query_selector("a, [class*='title']")
                date_elem = await item.query_selector("[class*='date'], time, .timestamp")

                title = await title_elem.inner_text() if title_elem else ""
                date = await date_elem.inner_text() if date_elem else ""

                link = await item.query_selector("a")
                url = await link.get_attribute("href") if link else ""

                if title.strip():
                    pages.append({
                        "title": title.strip(),
                        "modified": date.strip(),
                        "url": url if url.startswith("http") else f"{self.CANVAS_URL}{url}" if url else "",
                    })
            except Exception:
                continue

        return pages

    async def download_file(
        self,
        file_url: str,
        save_dir: str = "data/downloads",
        filename: Optional[str] = None
    ) -> Optional[str]:
        """
        Download a file from Canvas with proper handling for various file types.

        Handles:
        - Direct file URLs (e.g., /files/123/download)
        - Canvas file preview pages (extracts download button)
        - PDF viewer pages
        - Large files (streams to disk)

        Args:
            file_url: URL of the file or file preview page
            save_dir: Directory to save downloaded files
            filename: Optional filename (auto-detected if not provided)

        Returns:
            Path to downloaded file, or None if download failed
        """
        await self._ensure_logged_in()

        # Apply rate limiting
        if not await rate_limiter.wait_and_acquire("canvas", max_wait=30):
            logger.error("Rate limit exceeded for Canvas")
            return None

        # Validate and sanitize save path
        try:
            save_path = validate_save_path(save_dir)
            save_path.mkdir(parents=True, exist_ok=True)
        except ValueError as e:
            logger.error(f"Invalid save path: {e}")
            raise

        try:
            # Navigate to the file URL first to see what we're dealing with
            await self._page.goto(file_url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(1)

            current_url = self._page.url

            # Check if this is a file preview page (Canvas wraps files in a viewer)
            # Look for download button/link on the page
            download_btn = await self._page.query_selector(
                'a[download], '
                'a[href*="/download"], '
                'a[href*="download=1"], '
                '.file-download-btn, '
                '#file_content a[href*="files"], '
                'a.Button--primary[href*="download"], '
                '.ef-file-download-btn, '
                'a[title="Download"]'
            )

            if download_btn:
                # Found a download button - use Playwright's download handling
                download_url = await download_btn.get_attribute("href")

                if download_url:
                    # Make URL absolute if needed
                    if not download_url.startswith("http"):
                        download_url = f"{self.CANVAS_URL}{download_url}"

                    # Ensure download parameter is set
                    if "download" not in download_url:
                        separator = "&" if "?" in download_url else "?"
                        download_url = f"{download_url}{separator}download=1"

                    logger.info(f"Found download URL: {download_url}")

                    # Use expect_download to capture the download
                    async with self._page.expect_download(timeout=60000) as download_info:
                        await self._page.goto(download_url)

                    download = await download_info.value

                    # Get suggested filename or use provided one (sanitized)
                    suggested_name = download.suggested_filename
                    final_filename = sanitize_filename(filename or suggested_name or "downloaded_file")
                    final_path = save_path / final_filename

                    # Save the download
                    await download.save_as(str(final_path))
                    logger.info(f"Downloaded: {final_path}")
                    return str(final_path)

            # No download button found - try direct download approaches
            # Check if URL already has download parameter or is a direct file link
            if "/download" in current_url or "download=1" in current_url or current_url.endswith(('.pdf', '.docx', '.pptx', '.xlsx', '.zip')):
                # Try using expect_download with current page
                try:
                    async with self._page.expect_download(timeout=30000) as download_info:
                        # Trigger download by reloading or clicking
                        await self._page.reload()

                    download = await download_info.value
                    final_filename = sanitize_filename(filename or download.suggested_filename or "downloaded_file")
                    final_path = save_path / final_filename
                    await download.save_as(str(final_path))
                    logger.info(f"Downloaded: {final_path}")
                    return str(final_path)
                except Exception:
                    pass  # Fall through to direct fetch

            # Last resort: try to construct download URL from file preview URL
            # Canvas file URLs often look like /courses/123/files/456
            # The download URL would be /files/456/download
            file_id_match = re.search(r'/files/(\d+)', current_url)
            if file_id_match:
                file_id = file_id_match.group(1)
                direct_download_url = f"{self.CANVAS_URL}/files/{file_id}/download?download_frd=1"

                logger.info(f"Trying direct download URL: {direct_download_url}")

                try:
                    async with self._page.expect_download(timeout=60000) as download_info:
                        await self._page.goto(direct_download_url)

                    download = await download_info.value
                    final_filename = sanitize_filename(filename or download.suggested_filename or "downloaded_file")
                    final_path = save_path / final_filename
                    await download.save_as(str(final_path))
                    logger.info(f"Downloaded: {final_path}")
                    return str(final_path)
                except Exception as e:
                    logger.warning(f"Direct download failed: {e}")

            # If all else fails, try to get response body (works for small files)
            logger.warning("Falling back to response body method")
            response = await self._page.goto(file_url, timeout=30000)
            if response and response.ok:
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type:
                    # It's a file, not a page
                    content = await response.body()

                    # Try to get filename from headers
                    content_disposition = response.headers.get("content-disposition", "")
                    if "filename=" in content_disposition:
                        fn_match = re.search(r'filename[*]?=["\']?([^"\';\n]+)', content_disposition)
                        if fn_match:
                            filename = fn_match.group(1).strip()

                    final_filename = sanitize_filename(filename or "downloaded_file")
                    final_path = save_path / final_filename

                    with open(final_path, 'wb') as f:
                        f.write(content)
                    logger.info(f"Downloaded (fallback): {final_path}")
                    return str(final_path)

            logger.error("Could not download file - no download method succeeded")
            return None

        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return None

    async def download_course_file(
        self,
        course_url: str,
        file_name: str,
        save_dir: str = "data/downloads"
    ) -> Optional[str]:
        """
        Download a specific file from a course by name.

        Args:
            course_url: The course URL
            file_name: Name of the file to download (partial match supported)
            save_dir: Directory to save the file

        Returns:
            Path to downloaded file, or None if not found
        """
        # Get files list
        files = await self.get_course_files(course_url)

        # Find matching file
        file_name_lower = file_name.lower()
        matching_file = None

        for f in files:
            if file_name_lower in f.name.lower():
                matching_file = f
                break

        if not matching_file:
            logger.warning(f"File not found: {file_name}")
            return None

        if matching_file.file_type == "folder":
            logger.warning(f"'{file_name}' is a folder, not a file")
            return None

        logger.info(f"Found file: {matching_file.name}")
        return await self.download_file(matching_file.url, save_dir)

    async def get_course_assignments(self, course_url: str) -> list[CanvasAssignment]:
        """
        Get all assignments for a specific course.

        Args:
            course_url: The course URL

        Returns:
            List of CanvasAssignment with name, due date, points, status, url
        """
        await self._ensure_logged_in()

        assignments = []

        # Navigate to course assignments page
        if "/courses/" in course_url:
            assignments_url = f"{course_url}/assignments"
        else:
            assignments_url = course_url

        await self._page.goto(assignments_url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(2)  # Wait for dynamic content

        # Get course name for context
        course_name = ""
        title_elem = await self._page.query_selector(".ellipsis, h1, .course-title")
        if title_elem:
            course_name = (await title_elem.inner_text()).strip()

        # Find assignment rows - Canvas uses different structures
        # Try multiple selectors for different Canvas views
        rows = await self._page.query_selector_all(
            ".ig-row.ig-published, "  # Standard assignment row
            ".assignment, "  # Generic assignment class
            "li.assignment, "  # List item assignments
            ".assignment_group .ig-row, "  # Grouped assignments
            "[data-item-id]"  # Data attribute based
        )

        logger.info(f"Found {len(rows)} assignment rows")

        for row in rows:
            try:
                # Get assignment name and link
                name_elem = await row.query_selector(
                    "a.ig-title, "
                    "a.title, "
                    ".assignment-title a, "
                    "a[class*='title'], "
                    ".ig-info a"
                )

                if not name_elem:
                    continue

                name = (await name_elem.inner_text()).strip()
                url = await name_elem.get_attribute("href") or ""

                if not name or name in ["Assignments", ""]:
                    continue

                # Get due date
                due_elem = await row.query_selector(
                    ".due_date, "
                    ".assignment-date-due, "
                    ".datedue, "
                    "[class*='due'], "
                    ".ig-details .ig-info, "
                    "time"
                )
                due_date = ""
                if due_elem:
                    due_text = await due_elem.inner_text()
                    # Clean up the due date text
                    due_date = due_text.strip().replace("Due", "").replace("due", "").strip()

                # Get points
                points_elem = await row.query_selector(
                    ".points_possible, "
                    ".points, "
                    "[class*='points'], "
                    ".ig-info .points"
                )
                points = ""
                if points_elem:
                    points = (await points_elem.inner_text()).strip()

                # Check submission status
                status = "upcoming"
                status_elem = await row.query_selector(
                    ".submission-status, "
                    ".submitted, "
                    "[class*='status'], "
                    ".ig-info .status"
                )
                if status_elem:
                    status_text = (await status_elem.inner_text()).lower()
                    if "submitted" in status_text:
                        status = "submitted"
                    elif "missing" in status_text:
                        status = "missing"
                    elif "late" in status_text:
                        status = "late"

                # Check for graded indicator
                grade_elem = await row.query_selector(".grade, .score, [class*='grade']")
                if grade_elem:
                    grade_text = await grade_elem.inner_text()
                    if grade_text.strip():
                        status = "graded"

                assignments.append(CanvasAssignment(
                    name=name,
                    course=course_name,
                    due_date=due_date if due_date else None,
                    points=points if points else None,
                    status=status,
                    url=url if url.startswith("http") else f"{self.CANVAS_URL}{url}" if url else "",
                ))

            except Exception as e:
                logger.debug(f"Error parsing assignment row: {e}")
                continue

        # If no assignments found with standard selectors, try alternative approach
        if not assignments:
            # Try to get assignments from assignment groups
            groups = await self._page.query_selector_all(".assignment_group, .ig-list")
            for group in groups:
                group_name_elem = await group.query_selector(".ig-header-title, h2, .group_name")
                group_name = ""
                if group_name_elem:
                    group_name = (await group_name_elem.inner_text()).strip()

                items = await group.query_selector_all(".ig-row, .assignment, li")
                for item in items:
                    try:
                        link = await item.query_selector("a")
                        if not link:
                            continue

                        name = (await link.inner_text()).strip()
                        url = await link.get_attribute("href") or ""

                        if name and name not in ["Assignments", group_name, ""]:
                            # Get any visible date info
                            due_info = await item.query_selector(".screenreader-only, .due, time")
                            due_date = ""
                            if due_info:
                                due_date = (await due_info.inner_text()).strip()

                            assignments.append(CanvasAssignment(
                                name=name,
                                course=course_name,
                                due_date=due_date if due_date else None,
                                points=None,
                                status="upcoming",
                                url=url if url.startswith("http") else f"{self.CANVAS_URL}{url}" if url else "",
                            ))
                    except Exception:
                        continue

        return assignments

    async def get_assignment_details(self, assignment_url: str) -> CanvasAssignmentDetails:
        """
        Get detailed information from an individual assignment page.

        This navigates to the assignment page (e.g., /courses/69273/assignments/844402)
        and extracts the full description and all metadata.

        Args:
            assignment_url: Full URL or path to the assignment page

        Returns:
            CanvasAssignmentDetails with description and all metadata
        """
        await self._ensure_logged_in()

        # Make URL absolute if needed
        if not assignment_url.startswith("http"):
            assignment_url = f"{self.CANVAS_URL}{assignment_url}"

        await self._page.goto(assignment_url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(1)  # Wait for dynamic content

        # Get assignment name
        name = ""
        name_elem = await self._page.query_selector(
            "h1.title, "
            ".assignment-title h1, "
            "h1[class*='title'], "
            ".ig-header-title, "
            "#assignment_show h1"
        )
        if name_elem:
            name = (await name_elem.inner_text()).strip()

        # Get course name from breadcrumb or header
        course = ""
        course_elem = await self._page.query_selector(
            ".ellipsis[title], "
            "#breadcrumbs li:nth-child(2) a, "
            ".course-title"
        )
        if course_elem:
            course = (await course_elem.inner_text()).strip()

        # Get description - this is the main content we're after
        description = ""
        desc_elem = await self._page.query_selector(
            ".description.user_content, "
            ".assignment-description, "
            "#assignment_show .description, "
            ".user_content.enhanced, "
            ".user_content, "
            "[class*='description']"
        )
        if desc_elem:
            # Get inner text for clean text, or innerHTML for formatted
            description = (await desc_elem.inner_text()).strip()

        # Get due date
        due_date = None
        due_elem = await self._page.query_selector(
            ".date_text, "
            ".assignment_dates .date-due, "
            "td.due_date_display, "
            "[class*='due-date'], "
            ".assignment-dates tr:first-child td"
        )
        if due_elem:
            due_date = (await due_elem.inner_text()).strip()

        # Try alternate due date location
        if not due_date:
            dates_table = await self._page.query_selector(".assignment_dates, .dates")
            if dates_table:
                rows = await dates_table.query_selector_all("tr")
                for row in rows:
                    label = await row.query_selector("th, td:first-child")
                    value = await row.query_selector("td:last-child, td:nth-child(2)")
                    if label and value:
                        label_text = (await label.inner_text()).lower()
                        if "due" in label_text:
                            due_date = (await value.inner_text()).strip()
                            break

        # Get points possible
        points = None
        points_elem = await self._page.query_selector(
            ".points_possible, "
            ".assignment-points-possible, "
            "[class*='points']"
        )
        if points_elem:
            points_text = await points_elem.inner_text()
            # Clean up points text - often formatted as "X pts" or "X points possible"
            points = points_text.strip()

        # Get submission types
        submission_types = []
        submission_elem = await self._page.query_selector(
            ".submission_types, "
            ".assignment_submission_types, "
            "[class*='submission-type']"
        )
        if submission_elem:
            sub_text = await submission_elem.inner_text()
            # Parse submission types (often comma-separated)
            types = [t.strip() for t in sub_text.replace("Submission Types:", "").split(",")]
            submission_types = [t for t in types if t]

        # Get availability dates
        available_from = None
        available_until = None
        if dates_table := await self._page.query_selector(".assignment_dates, .dates"):
            rows = await dates_table.query_selector_all("tr")
            for row in rows:
                label = await row.query_selector("th, td:first-child")
                value = await row.query_selector("td:last-child, td:nth-child(2)")
                if label and value:
                    label_text = (await label.inner_text()).lower()
                    value_text = (await value.inner_text()).strip()
                    if "available from" in label_text or "available" in label_text and "until" not in label_text:
                        available_from = value_text
                    elif "until" in label_text:
                        available_until = value_text

        # Get attempts allowed
        attempts_allowed = None
        attempts_elem = await self._page.query_selector(
            ".allowed_attempts, "
            "[class*='attempts']"
        )
        if attempts_elem:
            attempts_allowed = (await attempts_elem.inner_text()).strip()

        # Get grading type
        grading_type = None
        grading_elem = await self._page.query_selector(
            ".grading_type, "
            "[class*='grading-type']"
        )
        if grading_elem:
            grading_type = (await grading_elem.inner_text()).strip()

        # Get rubric if present
        rubric = []
        rubric_container = await self._page.query_selector(
            "#rubric_full, "
            ".rubric_container, "
            ".rubric"
        )
        if rubric_container:
            criteria = await rubric_container.query_selector_all(
                ".criterion, "
                ".rubric_criterion, "
                "tr.criterion"
            )
            for criterion in criteria:
                try:
                    crit_name = await criterion.query_selector(
                        ".description_title, "
                        ".criterion_description, "
                        ".description"
                    )
                    crit_points = await criterion.query_selector(
                        ".points, "
                        ".criterion_points"
                    )

                    if crit_name:
                        rubric.append({
                            "criterion": (await crit_name.inner_text()).strip(),
                            "points": (await crit_points.inner_text()).strip() if crit_points else "",
                        })
                except Exception:
                    continue

        return CanvasAssignmentDetails(
            name=name,
            course=course,
            url=assignment_url,
            description=description,
            due_date=due_date,
            points=points,
            submission_types=submission_types if submission_types else None,
            available_from=available_from,
            available_until=available_until,
            attempts_allowed=attempts_allowed,
            grading_type=grading_type,
            rubric=rubric if rubric else None,
        )

    async def get_course_announcements(self, course_url: str, limit: int = 20) -> list[CanvasAnnouncement]:
        """
        Get announcements for a specific course.

        Args:
            course_url: The course URL
            limit: Maximum announcements to return
        """
        await self._ensure_logged_in()

        announcements = []

        # Navigate to course announcements
        if "/courses/" in course_url:
            ann_url = f"{course_url}/announcements"
        else:
            ann_url = course_url

        await self._page.goto(ann_url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(1)

        # Find announcement items
        ann_items = await self._page.query_selector_all(
            ".ic-announcement-row, .discussion-topic, [class*='announcement'], tr.announcement"
        )

        for item in ann_items[:limit]:
            try:
                title_elem = await item.query_selector("a.discussion-title, .title a, a, h3")
                date_elem = await item.query_selector(".timestamp, time, [class*='date'], .discussion-pubdate")
                preview_elem = await item.query_selector(".message, .discussion-summary, p, [class*='body']")

                title = await title_elem.inner_text() if title_elem else ""
                date = await date_elem.inner_text() if date_elem else ""
                preview = await preview_elem.inner_text() if preview_elem else ""

                link = await item.query_selector("a")
                url = await link.get_attribute("href") if link else ""

                if title.strip():
                    announcements.append(CanvasAnnouncement(
                        title=title.strip(),
                        course="",  # We're already in the course context
                        date=date.strip(),
                        preview=preview.strip()[:300],
                        url=url if url.startswith("http") else f"{self.CANVAS_URL}{url}" if url else "",
                    ))
            except Exception:
                continue

        return announcements

    async def get_course_schedule(self, course_url: str) -> dict:
        """
        Get course schedule/meeting times from the course home or syllabus.

        Args:
            course_url: The course URL

        Returns:
            dict with schedule info (days, times, location, instructor)
        """
        await self._ensure_logged_in()

        schedule = {
            "course_url": course_url,
            "meeting_times": [],
            "location": None,
            "instructor": None,
            "section": None,
        }

        # Try course home page first
        await self._page.goto(course_url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(1)

        # Get course title/section info
        title_elem = await self._page.query_selector("h2.course-title, .course-title, h1")
        if title_elem:
            title = await title_elem.inner_text()
            schedule["course_name"] = title.strip()
            # Parse section from title like "CMSC 25400 2,1"
            import re
            section_match = re.search(r'(\d+(?:,\d+)*)\s*(?:\(|$)', title)
            if section_match:
                schedule["section"] = section_match.group(1)

        # Look for schedule info in course home content
        content = await self._page.content()

        # Common patterns for meeting times
        time_patterns = [
            r'(Monday|Tuesday|Wednesday|Thursday|Friday|Mon|Tue|Wed|Thu|Fri|M|T|W|R|F)[,\s]*((?:Monday|Tuesday|Wednesday|Thursday|Friday|Mon|Tue|Wed|Thu|Fri|M|T|W|R|F)[,\s]*)*\s*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\s*[-–]\s*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'(MWF|TR|MW|TuTh|TTh)\s*(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})',
        ]

        for pattern in time_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                schedule["meeting_times"].append(" ".join(str(m) for m in match if m))

        # Look for instructor
        instructor_elem = await self._page.query_selector(
            ".instructor, [class*='instructor'], .teacher, a[href*='/users/']"
        )
        if instructor_elem:
            schedule["instructor"] = (await instructor_elem.inner_text()).strip()

        # Look for location
        location_patterns = [
            r'(Kent|Ryerson|Eckhart|Crerar|Stuart|Harper|Cobb|Pick|Jones|Hinds)\s*\d+',
            r'Room\s*\d+',
            r'[A-Z]+\s*\d{3,4}',
        ]
        for pattern in location_patterns:
            loc_match = re.search(pattern, content)
            if loc_match:
                schedule["location"] = loc_match.group(0)
                break

        # If no schedule found on home, try syllabus
        if not schedule["meeting_times"]:
            syllabus = await self.get_course_syllabus(course_url)
            if syllabus.get("content"):
                for pattern in time_patterns:
                    matches = re.findall(pattern, syllabus["content"], re.IGNORECASE)
                    for match in matches:
                        schedule["meeting_times"].append(" ".join(str(m) for m in match if m))

        return schedule

    async def get_course_people(self, course_url: str) -> dict:
        """
        Get instructors, TAs, and students from a course.

        Args:
            course_url: The course URL

        Returns:
            dict with instructors, tas, and student_count
        """
        await self._ensure_logged_in()

        result = {
            "instructors": [],
            "tas": [],
            "student_count": 0,
        }

        # Navigate to people page
        if "/courses/" in course_url:
            people_url = f"{course_url}/users"
        else:
            people_url = course_url

        await self._page.goto(people_url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(1)

        # Get role-based sections
        # Teachers/Instructors
        teacher_section = await self._page.query_selector("[data-view='teachers'], .teachers-list, #teacher-roster")
        if teacher_section:
            teacher_links = await teacher_section.query_selector_all("a.roster_user, .user_name a, a")
            for link in teacher_links:
                name = await link.inner_text()
                if name.strip():
                    result["instructors"].append(name.strip())

        # TAs
        ta_section = await self._page.query_selector("[data-view='tas'], .ta-list, #ta-roster")
        if ta_section:
            ta_links = await ta_section.query_selector_all("a.roster_user, .user_name a, a")
            for link in ta_links:
                name = await link.inner_text()
                if name.strip():
                    result["tas"].append(name.strip())

        # If no sections found, try the general roster
        if not result["instructors"]:
            all_users = await self._page.query_selector_all(".roster_user, .user-name, tr.user")
            for user in all_users:
                name_elem = await user.query_selector("a, .name")
                role_elem = await user.query_selector(".role, .enrollment-type, td:nth-child(2)")

                if name_elem:
                    name = await name_elem.inner_text()
                    role = await role_elem.inner_text() if role_elem else ""

                    if "teacher" in role.lower() or "instructor" in role.lower():
                        result["instructors"].append(name.strip())
                    elif "ta" in role.lower() or "assistant" in role.lower():
                        result["tas"].append(name.strip())

        # Get student count
        count_elem = await self._page.query_selector(".students-count, [class*='student-count'], .roster-tab[data-view='students'] .count")
        if count_elem:
            count_text = await count_elem.inner_text()
            import re
            count_match = re.search(r'\d+', count_text)
            if count_match:
                result["student_count"] = int(count_match.group())

        return result

    async def get_course_grades(self, course_url: str) -> list[dict]:
        """
        Get grades for a specific course.

        Args:
            course_url: The course URL

        Returns:
            List of assignment grades
        """
        await self._ensure_logged_in()

        grades = []

        # Navigate to course grades
        if "/courses/" in course_url:
            grades_url = f"{course_url}/grades"
        else:
            grades_url = course_url

        await self._page.goto(grades_url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(1)

        # Find grade rows
        rows = await self._page.query_selector_all(
            "#grades_summary tr.student_assignment, .assignment_graded, tr[class*='assignment']"
        )

        for row in rows:
            try:
                name_elem = await row.query_selector("th a, .title a, td:first-child a")
                score_elem = await row.query_selector(".grade, .score, td.points_possible, .what_if_score")
                points_elem = await row.query_selector(".points_possible, .possible, td:nth-child(3)")

                name = await name_elem.inner_text() if name_elem else ""
                score = await score_elem.inner_text() if score_elem else ""
                points = await points_elem.inner_text() if points_elem else ""

                if name.strip():
                    grades.append({
                        "assignment": name.strip(),
                        "score": score.strip(),
                        "points_possible": points.strip(),
                    })
            except Exception:
                continue

        # Get overall grade
        total_elem = await self._page.query_selector(
            ".final_grade, .total-grade, #submission_final-grade .grade"
        )
        if total_elem:
            total = await total_elem.inner_text()
            grades.append({
                "assignment": "TOTAL",
                "score": total.strip(),
                "points_possible": "100%",
            })

        return grades

    async def take_screenshot(self, path: str = "canvas_screenshot.png"):
        """Take a screenshot of the current page (useful for debugging)."""
        if self._page:
            await self._page.screenshot(path=path)
            logger.info(f"Screenshot saved to {path}")


# Convenience functions for sync usage
def run_canvas_login():
    """Run interactive Canvas login (opens browser window)."""
    async def _login():
        client = CanvasBrowser(headless=False)
        await client.start()
        success = await client.login(timeout=180)
        await client.stop()
        return success

    return asyncio.run(_login())
