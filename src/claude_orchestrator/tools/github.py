"""GitHub integration tools."""

import json

from mcp.server.fastmcp import FastMCP

from ..config import Config
from ..github_client import GitHubClient


def register_github_tools(mcp: FastMCP, config: Config) -> None:
	"""Register GitHub tools."""

	github_client = GitHubClient(
		token_file=str(config.data_dir / "credentials" / "github_token.txt")
	)

	@mcp.tool()
	async def setup_github(token: str) -> str:
		"""
		Configure GitHub with your personal access token.

		To get a token:
		1. Go to github.com/settings/tokens
		2. Click "Generate new token (classic)"
		3. Select scopes: repo, read:user, notifications
		4. Copy the token

		Args:
			token: Your GitHub personal access token
		"""
		github_client.save_token(token)
		try:
			user = github_client.get_current_user()
			return json.dumps({
				"success": True,
				"message": f"GitHub configured for {user['login']}",
				"user": user,
			})
		except Exception as e:
			return json.dumps({"error": f"Failed to verify token: {str(e)}"})

	@mcp.tool()
	async def get_github_repos(
		include_private: bool = True,
		include_forks: bool = False,
	) -> str:
		"""
		Get your GitHub repositories.

		Args:
			include_private: Include private repos (default: True)
			include_forks: Include forked repos (default: False)
		"""
		if not github_client.is_configured():
			return json.dumps({"error": "GitHub not configured. Use setup_github with your token."})
		try:
			repos = github_client.get_repos(include_private=include_private, include_forks=include_forks)
			return json.dumps([{
				"name": r.name, "full_name": r.full_name, "description": r.description,
				"url": r.url, "private": r.private, "language": r.language,
				"stars": r.stars, "open_issues": r.open_issues,
			} for r in repos], indent=2)
		except Exception as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def get_github_issues(repo_name: str, state: str = "open", limit: int = 20) -> str:
		"""
		Get issues for a GitHub repository.

		Args:
			repo_name: Repository name (e.g., 'owner/repo' or just 'repo' for yours)
			state: Issue state - 'open', 'closed', or 'all'
			limit: Maximum number to return
		"""
		if not github_client.is_configured():
			return json.dumps({"error": "GitHub not configured. Use setup_github with your token."})
		try:
			issues = github_client.get_issues(repo_name, state=state, limit=limit)
			return json.dumps([{
				"number": i.number, "title": i.title, "state": i.state,
				"labels": i.labels, "url": i.url, "is_pr": i.is_pull_request,
			} for i in issues], indent=2)
		except Exception as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def create_github_issue(repo_name: str, title: str, body: str = "", labels: str = "") -> str:
		"""
		Create a new GitHub issue.

		Args:
			repo_name: Repository name
			title: Issue title
			body: Issue body/description
			labels: Comma-separated labels (e.g., "bug,enhancement")
		"""
		if not github_client.is_configured():
			return json.dumps({"error": "GitHub not configured. Use setup_github with your token."})
		try:
			label_list = [lab.strip() for lab in labels.split(",") if lab.strip()] if labels else []
			issue = github_client.create_issue(repo_name=repo_name, title=title, body=body, labels=label_list)
			if issue:
				return json.dumps({"success": True, "issue_number": issue.number, "url": issue.url})
			return json.dumps({"error": "Failed to create issue"})
		except Exception as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def get_github_prs(repo_name: str, state: str = "open", limit: int = 20) -> str:
		"""
		Get pull requests for a repository.

		Args:
			repo_name: Repository name
			state: PR state - 'open', 'closed', or 'all'
			limit: Maximum number to return
		"""
		if not github_client.is_configured():
			return json.dumps({"error": "GitHub not configured. Use setup_github with your token."})
		try:
			prs = github_client.get_pull_requests(repo_name, state=state, limit=limit)
			return json.dumps([{
				"number": pr.number, "title": pr.title, "state": pr.state,
				"head": pr.head_branch, "base": pr.base_branch, "mergeable": pr.mergeable,
				"url": pr.url, "additions": pr.additions, "deletions": pr.deletions,
			} for pr in prs], indent=2)
		except Exception as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def get_github_notifications(unread_only: bool = True) -> str:
		"""
		Get your GitHub notifications.

		Args:
			unread_only: Only show unread notifications (default: True)
		"""
		if not github_client.is_configured():
			return json.dumps({"error": "GitHub not configured. Use setup_github with your token."})
		try:
			notifications = github_client.get_notifications(unread_only=unread_only)
			return json.dumps(notifications, indent=2)
		except Exception as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def search_github_repos(query: str, limit: int = 10) -> str:
		"""
		Search for GitHub repositories.

		Args:
			query: Search query (e.g., "machine learning python", "language:rust stars:>1000")
			limit: Maximum results to return
		"""
		if not github_client.is_configured():
			return json.dumps({"error": "GitHub not configured. Use setup_github with your token."})
		try:
			repos = github_client.search_repos(query=query, limit=limit)
			return json.dumps([{
				"name": r.full_name, "description": r.description,
				"url": r.url, "stars": r.stars, "language": r.language,
			} for r in repos], indent=2)
		except Exception as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def get_github_file(repo_name: str, file_path: str) -> str:
		"""
		Get content of a file from a GitHub repository.

		Args:
			repo_name: Repository name
			file_path: Path to file (e.g., "README.md", "src/main.py")
		"""
		if not github_client.is_configured():
			return json.dumps({"error": "GitHub not configured. Use setup_github with your token."})
		try:
			content = github_client.get_file_content(repo_name, file_path)
			if content:
				return json.dumps({"file": file_path, "content": content})
			return json.dumps({"error": f"File not found: {file_path}"})
		except Exception as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def comment_on_github_issue(repo_name: str, issue_number: int, comment: str) -> str:
		"""
		Add a comment to a GitHub issue or PR.

		Args:
			repo_name: Repository name
			issue_number: Issue or PR number
			comment: Comment text
		"""
		if not github_client.is_configured():
			return json.dumps({"error": "GitHub not configured. Use setup_github with your token."})
		try:
			success = github_client.add_comment_to_issue(repo_name, issue_number, comment)
			if success:
				return json.dumps({"success": True, "message": "Comment added"})
			return json.dumps({"error": "Failed to add comment"})
		except Exception as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def get_github_rate_limit() -> str:
		"""Check your GitHub API rate limit status."""
		if not github_client.is_configured():
			return json.dumps({"error": "GitHub not configured. Use setup_github with your token."})
		try:
			return json.dumps(github_client.get_rate_limit(), indent=2)
		except Exception as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def check_github_security() -> str:
		"""
		Check GitHub token security and permissions.

		Returns information about:
		- Current token scopes
		- Warnings about dangerous permissions
		- Recommendations for minimal scopes
		- Rate limit status
		"""
		if not github_client.is_configured():
			return json.dumps({"error": "GitHub not configured. Use setup_github with your token."})
		try:
			return json.dumps(github_client.check_token_scopes(), indent=2)
		except Exception as e:
			return json.dumps({"error": str(e)})
