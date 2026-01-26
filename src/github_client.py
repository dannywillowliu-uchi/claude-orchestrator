"""GitHub API Client for repository and issue management."""

import os
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

from github import Github, Auth
from github.Repository import Repository
from github.Issue import Issue
from github.PullRequest import PullRequest
from github.GithubException import GithubException

from .security import rate_limiter

logger = logging.getLogger(__name__)

# Token scopes that grant excessive permissions
DANGEROUS_SCOPES = {
    "delete_repo": "Can delete repositories",
    "admin:org": "Full admin access to organizations",
    "admin:public_key": "Can manage SSH keys",
    "admin:repo_hook": "Can manage repository webhooks",
    "admin:org_hook": "Can manage organization webhooks",
    "write:packages": "Can publish packages",
    "delete:packages": "Can delete packages",
    "admin:gpg_key": "Can manage GPG keys",
}

# Recommended minimal scopes for this application
RECOMMENDED_SCOPES = ["repo", "read:user", "notifications"]


@dataclass
class GitHubRepo:
    """Structured repository data."""
    name: str
    full_name: str
    description: Optional[str]
    url: str
    private: bool
    language: Optional[str]
    stars: int
    forks: int
    open_issues: int
    default_branch: str
    updated_at: str


@dataclass
class GitHubIssue:
    """Structured issue data."""
    number: int
    title: str
    state: str
    body: Optional[str]
    labels: list[str]
    assignees: list[str]
    created_at: str
    updated_at: str
    url: str
    is_pull_request: bool


@dataclass
class GitHubPR:
    """Structured pull request data."""
    number: int
    title: str
    state: str
    body: Optional[str]
    head_branch: str
    base_branch: str
    mergeable: Optional[bool]
    labels: list[str]
    created_at: str
    updated_at: str
    url: str
    additions: int
    deletions: int
    changed_files: int


class GitHubClient:
    """Client for GitHub API operations."""

    TOKEN_FILE = "data/credentials/github_token.txt"

    def __init__(self, token: Optional[str] = None, token_file: str = TOKEN_FILE):
        self.token_file = Path(token_file)
        self._token = token
        self._github: Optional[Github] = None

    @property
    def token(self) -> Optional[str]:
        """Get GitHub token from file or environment."""
        if self._token:
            return self._token

        # Try environment variable
        token = os.getenv("GITHUB_TOKEN")
        if token:
            return token

        # Try token file
        if self.token_file.exists():
            return self.token_file.read_text().strip()

        return None

    def save_token(self, token: str):
        """Save GitHub token to file."""
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(token)
        self._token = token
        self._github = None  # Reset connection

    def is_configured(self) -> bool:
        """Check if GitHub is configured with a token."""
        return self.token is not None

    def _get_github(self) -> Github:
        """Get or create GitHub API instance."""
        if self._github is None:
            token = self.token
            if not token:
                raise ValueError(
                    "GitHub token not configured. "
                    "Generate one at github.com/settings/tokens"
                )
            auth = Auth.Token(token)
            self._github = Github(auth=auth)

            # Check token scopes on first connection
            self._check_token_scopes()

        return self._github

    def _check_token_scopes(self):
        """Check token scopes and warn about dangerous permissions."""
        if self._github is None:
            return

        try:
            # Get OAuth scopes from rate limit call (includes X-OAuth-Scopes header)
            rate_limit = self._github.get_rate_limit()

            # PyGithub exposes scopes through requester
            scopes = getattr(self._github, '_Github__requester', None)
            if scopes and hasattr(scopes, 'oauth_scopes'):
                oauth_scopes = scopes.oauth_scopes or []

                # Check for dangerous scopes
                warnings = []
                for scope in oauth_scopes:
                    if scope in DANGEROUS_SCOPES:
                        warnings.append(f"  - {scope}: {DANGEROUS_SCOPES[scope]}")

                if warnings:
                    logger.warning(
                        "GitHub token has potentially dangerous scopes:\n"
                        + "\n".join(warnings)
                        + "\n  Consider creating a new token with minimal permissions: "
                        + ", ".join(RECOMMENDED_SCOPES)
                    )

        except Exception as e:
            logger.debug(f"Could not check token scopes: {e}")

    def check_token_scopes(self) -> dict:
        """
        Check the current token's scopes and return a security report.

        Returns:
            dict with 'scopes', 'warnings', and 'recommendations'
        """
        self._get_github()  # Ensure connected

        result = {
            "scopes": [],
            "warnings": [],
            "recommendations": [],
            "rate_limit": {},
        }

        try:
            # Get rate limit info
            rate_limit = self._github.get_rate_limit()
            result["rate_limit"] = {
                "core_remaining": rate_limit.core.remaining,
                "core_limit": rate_limit.core.limit,
                "search_remaining": rate_limit.search.remaining,
                "search_limit": rate_limit.search.limit,
            }

            # Try to get scopes
            scopes = getattr(self._github, '_Github__requester', None)
            if scopes and hasattr(scopes, 'oauth_scopes'):
                oauth_scopes = scopes.oauth_scopes or []
                result["scopes"] = list(oauth_scopes)

                # Check for dangerous scopes
                for scope in oauth_scopes:
                    if scope in DANGEROUS_SCOPES:
                        result["warnings"].append({
                            "scope": scope,
                            "risk": DANGEROUS_SCOPES[scope],
                        })

                # Check for missing recommended scopes
                for scope in RECOMMENDED_SCOPES:
                    if scope not in oauth_scopes:
                        result["recommendations"].append(
                            f"Consider adding '{scope}' scope for full functionality"
                        )

        except Exception as e:
            result["error"] = str(e)

        return result

    def get_current_user(self) -> dict:
        """Get current authenticated user info."""
        gh = self._get_github()
        user = gh.get_user()
        return {
            "login": user.login,
            "name": user.name,
            "email": user.email,
            "public_repos": user.public_repos,
            "private_repos": user.owned_private_repos,
            "followers": user.followers,
        }

    def get_repos(
        self,
        include_private: bool = True,
        include_forks: bool = False,
        sort: str = "updated",
    ) -> list[GitHubRepo]:
        """
        Get user's repositories.

        Args:
            include_private: Include private repositories
            include_forks: Include forked repositories
            sort: Sort by 'updated', 'created', 'pushed', 'name'
        """
        gh = self._get_github()
        user = gh.get_user()

        repos = []
        for repo in user.get_repos(sort=sort):
            if not include_private and repo.private:
                continue
            if not include_forks and repo.fork:
                continue

            repos.append(GitHubRepo(
                name=repo.name,
                full_name=repo.full_name,
                description=repo.description,
                url=repo.html_url,
                private=repo.private,
                language=repo.language,
                stars=repo.stargazers_count,
                forks=repo.forks_count,
                open_issues=repo.open_issues_count,
                default_branch=repo.default_branch,
                updated_at=repo.updated_at.isoformat() if repo.updated_at else "",
            ))

        return repos

    def get_repo(self, repo_name: str) -> Optional[Repository]:
        """
        Get a specific repository.

        Args:
            repo_name: Full name like 'owner/repo' or just 'repo' for your own
        """
        gh = self._get_github()
        try:
            if "/" not in repo_name:
                user = gh.get_user()
                repo_name = f"{user.login}/{repo_name}"
            return gh.get_repo(repo_name)
        except GithubException as e:
            logger.error(f"Error getting repo {repo_name}: {e}")
            return None

    def get_issues(
        self,
        repo_name: str,
        state: str = "open",
        labels: Optional[list[str]] = None,
        limit: int = 20,
    ) -> list[GitHubIssue]:
        """
        Get issues for a repository.

        Args:
            repo_name: Repository name
            state: 'open', 'closed', or 'all'
            labels: Filter by labels
            limit: Maximum number of issues to return
        """
        repo = self.get_repo(repo_name)
        if not repo:
            return []

        issues = []
        try:
            issue_list = repo.get_issues(state=state, labels=labels or [])
            for issue in issue_list[:limit]:
                issues.append(GitHubIssue(
                    number=issue.number,
                    title=issue.title,
                    state=issue.state,
                    body=issue.body,
                    labels=[l.name for l in issue.labels],
                    assignees=[a.login for a in issue.assignees],
                    created_at=issue.created_at.isoformat() if issue.created_at else "",
                    updated_at=issue.updated_at.isoformat() if issue.updated_at else "",
                    url=issue.html_url,
                    is_pull_request=issue.pull_request is not None,
                ))
        except GithubException as e:
            logger.error(f"Error getting issues: {e}")

        return issues

    def create_issue(
        self,
        repo_name: str,
        title: str,
        body: str = "",
        labels: Optional[list[str]] = None,
        assignees: Optional[list[str]] = None,
    ) -> Optional[GitHubIssue]:
        """Create a new issue."""
        repo = self.get_repo(repo_name)
        if not repo:
            return None

        try:
            issue = repo.create_issue(
                title=title,
                body=body,
                labels=labels or [],
                assignees=assignees or [],
            )
            return GitHubIssue(
                number=issue.number,
                title=issue.title,
                state=issue.state,
                body=issue.body,
                labels=[l.name for l in issue.labels],
                assignees=[a.login for a in issue.assignees],
                created_at=issue.created_at.isoformat() if issue.created_at else "",
                updated_at=issue.updated_at.isoformat() if issue.updated_at else "",
                url=issue.html_url,
                is_pull_request=False,
            )
        except GithubException as e:
            logger.error(f"Error creating issue: {e}")
            return None

    def get_pull_requests(
        self,
        repo_name: str,
        state: str = "open",
        limit: int = 20,
    ) -> list[GitHubPR]:
        """Get pull requests for a repository."""
        repo = self.get_repo(repo_name)
        if not repo:
            return []

        prs = []
        try:
            for pr in repo.get_pulls(state=state)[:limit]:
                prs.append(GitHubPR(
                    number=pr.number,
                    title=pr.title,
                    state=pr.state,
                    body=pr.body,
                    head_branch=pr.head.ref,
                    base_branch=pr.base.ref,
                    mergeable=pr.mergeable,
                    labels=[l.name for l in pr.labels],
                    created_at=pr.created_at.isoformat() if pr.created_at else "",
                    updated_at=pr.updated_at.isoformat() if pr.updated_at else "",
                    url=pr.html_url,
                    additions=pr.additions,
                    deletions=pr.deletions,
                    changed_files=pr.changed_files,
                ))
        except GithubException as e:
            logger.error(f"Error getting pull requests: {e}")

        return prs

    def get_notifications(self, unread_only: bool = True) -> list[dict]:
        """Get GitHub notifications."""
        gh = self._get_github()
        notifications = []

        try:
            for notif in gh.get_user().get_notifications(all=not unread_only):
                notifications.append({
                    "id": notif.id,
                    "reason": notif.reason,
                    "unread": notif.unread,
                    "subject_title": notif.subject.title,
                    "subject_type": notif.subject.type,
                    "repository": notif.repository.full_name,
                    "updated_at": notif.updated_at.isoformat() if notif.updated_at else "",
                    "url": notif.subject.url,
                })
        except GithubException as e:
            logger.error(f"Error getting notifications: {e}")

        return notifications

    def search_repos(
        self,
        query: str,
        sort: str = "stars",
        limit: int = 10,
    ) -> list[GitHubRepo]:
        """Search for repositories."""
        gh = self._get_github()
        repos = []

        try:
            for repo in gh.search_repositories(query=query, sort=sort)[:limit]:
                repos.append(GitHubRepo(
                    name=repo.name,
                    full_name=repo.full_name,
                    description=repo.description,
                    url=repo.html_url,
                    private=repo.private,
                    language=repo.language,
                    stars=repo.stargazers_count,
                    forks=repo.forks_count,
                    open_issues=repo.open_issues_count,
                    default_branch=repo.default_branch,
                    updated_at=repo.updated_at.isoformat() if repo.updated_at else "",
                ))
        except GithubException as e:
            logger.error(f"Error searching repos: {e}")

        return repos

    def get_repo_contents(
        self,
        repo_name: str,
        path: str = "",
    ) -> list[dict]:
        """Get contents of a repository directory."""
        repo = self.get_repo(repo_name)
        if not repo:
            return []

        contents = []
        try:
            for content in repo.get_contents(path):
                contents.append({
                    "name": content.name,
                    "path": content.path,
                    "type": content.type,
                    "size": content.size,
                    "download_url": content.download_url,
                })
        except GithubException as e:
            logger.error(f"Error getting repo contents: {e}")

        return contents

    def get_file_content(
        self,
        repo_name: str,
        file_path: str,
    ) -> Optional[str]:
        """Get content of a specific file."""
        repo = self.get_repo(repo_name)
        if not repo:
            return None

        try:
            content = repo.get_contents(file_path)
            if content.type == "file":
                return content.decoded_content.decode("utf-8")
        except GithubException as e:
            logger.error(f"Error getting file content: {e}")

        return None

    def add_comment_to_issue(
        self,
        repo_name: str,
        issue_number: int,
        comment: str,
    ) -> bool:
        """Add a comment to an issue or PR."""
        repo = self.get_repo(repo_name)
        if not repo:
            return False

        try:
            issue = repo.get_issue(issue_number)
            issue.create_comment(comment)
            return True
        except GithubException as e:
            logger.error(f"Error adding comment: {e}")
            return False

    def close_issue(self, repo_name: str, issue_number: int) -> bool:
        """Close an issue."""
        repo = self.get_repo(repo_name)
        if not repo:
            return False

        try:
            issue = repo.get_issue(issue_number)
            issue.edit(state="closed")
            return True
        except GithubException as e:
            logger.error(f"Error closing issue: {e}")
            return False

    def get_rate_limit(self) -> dict:
        """Get current rate limit status."""
        gh = self._get_github()
        rate = gh.get_rate_limit()
        return {
            "core": {
                "limit": rate.core.limit,
                "remaining": rate.core.remaining,
                "reset": rate.core.reset.isoformat(),
            },
            "search": {
                "limit": rate.search.limit,
                "remaining": rate.search.remaining,
                "reset": rate.search.reset.isoformat(),
            },
        }
