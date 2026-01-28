"""Security utilities for task-automation-mcp.

Provides:
- Path validation to prevent directory traversal
- Rate limiting for external APIs
- Audit logging for tool invocations
- Secure session storage
"""

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Path Validation
# =============================================================================

# Allowed base directories for file operations
ALLOWED_DOWNLOAD_DIRS = [
    "data/downloads",
    "data/exports",
    "data/canvas",
]

# Directories that should never be accessed
FORBIDDEN_PATHS = [
    "/etc",
    "/var",
    "/usr",
    "/bin",
    "/sbin",
    "/System",
    "/Library",
    "/private",
    "~/.ssh",
    "~/.gnupg",
    "~/.aws",
    "~/.config",
]


def get_project_root() -> Path:
    """Get the data directory for the application."""
    from .config import get_config
    return get_config().data_dir


def validate_save_path(save_dir: str, filename: Optional[str] = None) -> Path:
    """
    Validate and sanitize a save path to prevent directory traversal attacks.

    Args:
        save_dir: The directory to save to
        filename: Optional filename

    Returns:
        Safe absolute path

    Raises:
        ValueError: If path is outside allowed directories or forbidden
    """
    project_root = get_project_root()

    # Expand user home directory
    save_dir_expanded = os.path.expanduser(save_dir)

    # Check for forbidden paths
    for forbidden in FORBIDDEN_PATHS:
        forbidden_expanded = os.path.expanduser(forbidden)
        if save_dir_expanded.startswith(forbidden_expanded):
            raise ValueError(f"Access denied: {save_dir} is in a protected directory")

    # If it's a relative path, make it relative to project root
    if not os.path.isabs(save_dir_expanded):
        full_path = project_root / save_dir_expanded
    else:
        full_path = Path(save_dir_expanded)

    # Resolve to absolute path (this resolves .. and symlinks)
    try:
        resolved_path = full_path.resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Invalid path: {save_dir}") from e

    # Check if resolved path is within allowed directories
    allowed = False

    # Allow paths within project root's data directory
    project_data = (project_root / "data").resolve()
    if str(resolved_path).startswith(str(project_data)):
        allowed = True

    # Allow paths in user's home directory (but not hidden/config dirs)
    home_dir = Path.home().resolve()
    if str(resolved_path).startswith(str(home_dir)):
        # Check it's not a hidden directory
        relative_to_home = resolved_path.relative_to(home_dir)
        parts = relative_to_home.parts
        if not any(part.startswith('.') for part in parts):
            allowed = True

    if not allowed:
        raise ValueError(
            f"Access denied: {save_dir} is outside allowed directories. "
            f"Use a path within data/ or your home directory."
        )

    # Add filename if provided
    if filename:
        # Sanitize filename
        safe_filename = sanitize_filename(filename)
        resolved_path = resolved_path / safe_filename

    return resolved_path


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent directory traversal and invalid characters.

    Args:
        filename: The filename to sanitize

    Returns:
        Safe filename
    """
    # Remove any path components
    filename = os.path.basename(filename)

    # Remove null bytes and other dangerous characters
    dangerous_chars = ['\x00', '/', '\\', '..', ':', '*', '?', '"', '<', '>', '|']
    for char in dangerous_chars:
        filename = filename.replace(char, '_')

    # Limit length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255 - len(ext)] + ext

    # Don't allow empty or dot-only filenames
    if not filename or filename in ('.', '..'):
        filename = 'unnamed_file'

    return filename


# =============================================================================
# Rate Limiting
# =============================================================================

@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    min_interval_seconds: float = 0.5  # Minimum time between requests


@dataclass
class RateLimitState:
    """State tracking for rate limiter."""
    minute_count: int = 0
    hour_count: int = 0
    minute_reset: float = 0
    hour_reset: float = 0
    last_request: float = 0


class RateLimiter:
    """
    Rate limiter for external API calls.

    Supports per-minute and per-hour limits with minimum intervals.
    """

    def __init__(self):
        self._states: dict[str, RateLimitState] = defaultdict(RateLimitState)
        self._configs: dict[str, RateLimitConfig] = {
            "github": RateLimitConfig(
                requests_per_minute=30,
                requests_per_hour=500,  # Conservative vs 5000 limit
                min_interval_seconds=0.5,
            ),
            "canvas": RateLimitConfig(
                requests_per_minute=20,
                requests_per_hour=300,
                min_interval_seconds=1.0,  # Be gentle with browser automation
            ),
            "google": RateLimitConfig(
                requests_per_minute=60,
                requests_per_hour=1000,
                min_interval_seconds=0.1,
            ),
            "telegram": RateLimitConfig(
                requests_per_minute=25,
                requests_per_hour=500,
                min_interval_seconds=0.1,
            ),
        }
        self._lock = asyncio.Lock()

    def configure(self, service: str, config: RateLimitConfig):
        """Configure rate limits for a service."""
        self._configs[service] = config

    async def acquire(self, service: str) -> bool:
        """
        Acquire permission to make a request.

        Args:
            service: The service name (github, canvas, google, telegram)

        Returns:
            True if request is allowed, False if rate limited
        """
        async with self._lock:
            config = self._configs.get(service, RateLimitConfig())
            state = self._states[service]
            now = time.time()

            # Reset counters if windows have passed
            if now >= state.minute_reset:
                state.minute_count = 0
                state.minute_reset = now + 60

            if now >= state.hour_reset:
                state.hour_count = 0
                state.hour_reset = now + 3600

            # Check limits
            if state.minute_count >= config.requests_per_minute:
                logger.warning(f"Rate limit hit for {service}: {state.minute_count}/min")
                return False

            if state.hour_count >= config.requests_per_hour:
                logger.warning(f"Rate limit hit for {service}: {state.hour_count}/hour")
                return False

            # Check minimum interval
            time_since_last = now - state.last_request
            if time_since_last < config.min_interval_seconds:
                wait_time = config.min_interval_seconds - time_since_last
                await asyncio.sleep(wait_time)

            # Update state
            state.minute_count += 1
            state.hour_count += 1
            state.last_request = time.time()

            return True

    async def wait_and_acquire(self, service: str, max_wait: float = 60) -> bool:
        """
        Wait for rate limit to clear and acquire permission.

        Args:
            service: The service name
            max_wait: Maximum seconds to wait

        Returns:
            True if acquired, False if timed out
        """
        start = time.time()
        while time.time() - start < max_wait:
            if await self.acquire(service):
                return True
            await asyncio.sleep(1)
        return False

    def get_status(self, service: str) -> dict:
        """Get current rate limit status for a service."""
        config = self._configs.get(service, RateLimitConfig())
        state = self._states[service]
        now = time.time()

        return {
            "service": service,
            "minute_remaining": max(0, config.requests_per_minute - state.minute_count),
            "hour_remaining": max(0, config.requests_per_hour - state.hour_count),
            "minute_reset_in": max(0, state.minute_reset - now),
            "hour_reset_in": max(0, state.hour_reset - now),
        }


# Global rate limiter instance
rate_limiter = RateLimiter()


def rate_limited(service: str):
    """
    Decorator to apply rate limiting to async functions.

    Usage:
        @rate_limited("github")
        async def call_github_api():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            if not await rate_limiter.wait_and_acquire(service):
                raise RuntimeError(f"Rate limit exceeded for {service}")
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# =============================================================================
# Audit Logging
# =============================================================================

class AuditLogger:
    """
    Audit logger for tracking MCP tool invocations.

    Logs all tool calls with timestamps, arguments, and results.
    """

    def __init__(self, log_dir: str = None):
        # Use absolute path based on project root
        if log_dir is None:
            log_dir = get_project_root() / "data" / "logs"
        self.log_dir = Path(log_dir)
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Fall back to temp directory if project dir isn't writable
            import tempfile
            self.log_dir = Path(tempfile.gettempdir()) / "task-automation-mcp" / "logs"
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "audit.jsonl"
        self._lock = asyncio.Lock()

    async def log_tool_call(
        self,
        tool_name: str,
        args: dict,
        result: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ):
        """
        Log a tool invocation.

        Args:
            tool_name: Name of the MCP tool
            args: Arguments passed to the tool (sanitized)
            result: Result summary (truncated)
            error: Error message if failed
            duration_ms: Execution time in milliseconds
        """
        # Sanitize args - remove sensitive data
        safe_args = self._sanitize_args(args)

        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "tool": tool_name,
            "args": safe_args,
            "success": error is None,
            "duration_ms": duration_ms,
        }

        if error:
            entry["error"] = error[:500]  # Truncate errors

        if result:
            # Only log result summary, not full content
            entry["result_length"] = len(result)
            entry["result_preview"] = result[:100] + "..." if len(result) > 100 else result

        async with self._lock:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def _sanitize_args(self, args: dict) -> dict:
        """Remove sensitive data from arguments."""
        sensitive_keys = ["password", "token", "secret", "api_key", "credentials"]

        safe_args = {}
        for key, value in args.items():
            if any(s in key.lower() for s in sensitive_keys):
                safe_args[key] = "[REDACTED]"
            elif isinstance(value, str) and len(value) > 500:
                safe_args[key] = value[:500] + "...[truncated]"
            else:
                safe_args[key] = value

        return safe_args

    async def get_recent_logs(self, limit: int = 100) -> list[dict]:
        """Get recent audit log entries."""
        entries = []

        if not self.log_file.exists():
            return entries

        with open(self.log_file, "r") as f:
            lines = f.readlines()

        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return entries


# Global audit logger instance
audit_logger = AuditLogger()


def audited(func: Callable) -> Callable:
    """
    Decorator to add audit logging to MCP tools.

    Usage:
        @mcp.tool()
        @audited
        async def my_tool(arg1: str) -> str:
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs) -> Any:
        start_time = time.time()
        error = None
        result = None

        try:
            result = await func(*args, **kwargs)
            return result
        except Exception as e:
            error = str(e)
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            await audit_logger.log_tool_call(
                tool_name=func.__name__,
                args=kwargs,
                result=result if isinstance(result, str) else str(result)[:500] if result else None,
                error=error,
                duration_ms=duration_ms,
            )

    return wrapper


# =============================================================================
# Secure Session Storage (macOS Keychain)
# =============================================================================

class SecureStorage:
    """
    Secure storage using macOS Keychain for sensitive data.

    Falls back to encrypted file storage if Keychain is unavailable.
    """

    SERVICE_NAME = "task-automation-mcp"

    def __init__(self):
        self._keychain_available = self._check_keychain()
        # Use absolute path based on project root
        self._fallback_dir = get_project_root() / "data" / "secure"
        try:
            self._fallback_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Fall back to temp directory if project dir isn't writable
            import tempfile
            self._fallback_dir = Path(tempfile.gettempdir()) / "task-automation-mcp" / "secure"
            self._fallback_dir.mkdir(parents=True, exist_ok=True)

    def _check_keychain(self) -> bool:
        """Check if macOS Keychain is available."""
        try:
            result = subprocess.run(
                ["security", "help"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def store(self, key: str, value: str) -> bool:
        """
        Store a value securely.

        Args:
            key: The key/identifier
            value: The value to store

        Returns:
            True if successful
        """
        if self._keychain_available:
            return self._store_keychain(key, value)
        else:
            return self._store_encrypted_file(key, value)

    def retrieve(self, key: str) -> Optional[str]:
        """
        Retrieve a stored value.

        Args:
            key: The key/identifier

        Returns:
            The stored value, or None if not found
        """
        if self._keychain_available:
            return self._retrieve_keychain(key)
        else:
            return self._retrieve_encrypted_file(key)

    def delete(self, key: str) -> bool:
        """Delete a stored value."""
        if self._keychain_available:
            return self._delete_keychain(key)
        else:
            return self._delete_encrypted_file(key)

    def _store_keychain(self, key: str, value: str) -> bool:
        """Store in macOS Keychain."""
        try:
            # Delete existing if present
            self._delete_keychain(key)

            # Add new entry
            result = subprocess.run(
                [
                    "security", "add-generic-password",
                    "-a", key,
                    "-s", self.SERVICE_NAME,
                    "-w", value,
                    "-U",  # Update if exists
                ],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Keychain store failed: {e}")
            return False

    def _retrieve_keychain(self, key: str) -> Optional[str]:
        """Retrieve from macOS Keychain."""
        try:
            result = subprocess.run(
                [
                    "security", "find-generic-password",
                    "-a", key,
                    "-s", self.SERVICE_NAME,
                    "-w",  # Output password only
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception as e:
            logger.error(f"Keychain retrieve failed: {e}")
            return None

    def _delete_keychain(self, key: str) -> bool:
        """Delete from macOS Keychain."""
        try:
            result = subprocess.run(
                [
                    "security", "delete-generic-password",
                    "-a", key,
                    "-s", self.SERVICE_NAME,
                ],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _get_encryption_key(self) -> bytes:
        """Get or create encryption key for fallback storage."""
        key_file = self._fallback_dir / ".key"

        if key_file.exists():
            with open(key_file, "rb") as f:
                return f.read()
        else:
            # Generate new key
            key = os.urandom(32)
            with open(key_file, "wb") as f:
                f.write(key)
            os.chmod(key_file, 0o600)
            return key

    def _store_encrypted_file(self, key: str, value: str) -> bool:
        """Store as encrypted file (fallback)."""
        try:
            # Simple XOR encryption with key derivation
            enc_key = self._get_encryption_key()
            key_hash = hashlib.sha256(key.encode() + enc_key).digest()

            value_bytes = value.encode()
            encrypted = bytes(b ^ key_hash[i % 32] for i, b in enumerate(value_bytes))

            file_path = self._fallback_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.enc"
            with open(file_path, "wb") as f:
                f.write(encrypted)
            os.chmod(file_path, 0o600)

            return True
        except Exception as e:
            logger.error(f"Encrypted file store failed: {e}")
            return False

    def _retrieve_encrypted_file(self, key: str) -> Optional[str]:
        """Retrieve from encrypted file (fallback)."""
        try:
            file_path = self._fallback_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.enc"

            if not file_path.exists():
                return None

            enc_key = self._get_encryption_key()
            key_hash = hashlib.sha256(key.encode() + enc_key).digest()

            with open(file_path, "rb") as f:
                encrypted = f.read()

            decrypted = bytes(b ^ key_hash[i % 32] for i, b in enumerate(encrypted))
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Encrypted file retrieve failed: {e}")
            return None

    def _delete_encrypted_file(self, key: str) -> bool:
        """Delete encrypted file (fallback)."""
        try:
            file_path = self._fallback_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.enc"
            if file_path.exists():
                file_path.unlink()
            return True
        except Exception:
            return False


# Global secure storage instance
secure_storage = SecureStorage()
