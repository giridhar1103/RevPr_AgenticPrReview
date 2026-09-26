"""GitHub REST client for public repositories and pull requests."""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from .config import settings

API = "https://api.github.com"

_REPO_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100}?)"
    r"(?:\.git)?(?:/(?:tree|blob)/[^?#]+)?/?(?:[?#].*)?$"
)
_PR_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})"
    r"/pull/(\d{1,7})(?:/[a-z]*)?/?(?:[?#].*)?$"
)


class GitHubError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def parse_repo_url(url: str) -> str:
    m = _REPO_RE.match(url.strip())
    if not m or m.group(2) in (".", ".."):
        raise GitHubError("Expected a URL like https://github.com/owner/repo")
    return f"{m.group(1)}/{m.group(2)}".lower()


def parse_pr_url(url: str) -> tuple[str, int]:
    m = _PR_RE.match(url.strip())
    if not m:
        raise GitHubError("Expected a URL like https://github.com/owner/repo/pull/123")
    return f"{m.group(1)}/{m.group(2)}".lower(), int(m.group(3))


@dataclass
class RepoInfo:
    full_name: str
    default_branch: str
    size_kb: int
    stars: int
    description: str
    head_sha: str
    language: str | None


@dataclass
class PRFile:
    path: str
    status: str  # added, modified, removed, renamed
    additions: int
    deletions: int
    patch: str | None
    previous_path: str | None


@dataclass
class PRInfo:
    repo: str
    number: int
    title: str
    body: str
    author: str
    state: str
    merged: bool
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    additions: int
    deletions: int
    changed_files: int
    commits: list[dict]
    files: list[PRFile]
    review_comments: list[dict]
    issue_comments: list[dict]
    url: str


class GitHub:
    def __init__(self, token: str | None = None):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "revpr",
        }
        token = token if token is not None else settings.github_token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(base_url=API, headers=headers, timeout=30)

    def _get(self, path: str, **params) -> httpx.Response:
        r = self.client.get(path, params=params or None)
        if r.status_code == 404:
            raise GitHubError("Not found, or the repository is private", 404)
        if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubError("GitHub rate limit reached, try again later", 429)
        if r.status_code >= 400:
            raise GitHubError(f"GitHub API error {r.status_code}", 502)
        return r

    def _paged(self, path: str, limit: int) -> list[dict]:
        out: list[dict] = []
        page = 1
        while len(out) < limit:
            batch = self._get(path, per_page=100, page=page).json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out[:limit]

    def repo(self, full_name: str) -> RepoInfo:
        data = self._get(f"/repos/{full_name}").json()
        if data.get("private"):
            raise GitHubError("Only public repositories are supported", 403)
        branch = data["default_branch"]
        head = self._get(f"/repos/{full_name}/commits/{branch}").json()["sha"]
        return RepoInfo(
            full_name=data["full_name"].lower(), default_branch=branch,
            size_kb=int(data.get("size") or 0), stars=int(data.get("stargazers_count") or 0),
            description=data.get("description") or "", head_sha=head,
            language=data.get("language"),
        )

    def pull(self, full_name: str, number: int, with_discussion: bool = True) -> PRInfo:
        d = self._get(f"/repos/{full_name}/pulls/{number}").json()
        files = [
            PRFile(
                path=f["filename"], status=f["status"], additions=f["additions"],
                deletions=f["deletions"], patch=f.get("patch"),
                previous_path=f.get("previous_filename"),
            )
            for f in self._paged(f"/repos/{full_name}/pulls/{number}/files", 300)
        ]
        commits = [
            {"sha": c["sha"], "message": c["commit"]["message"][:500],
             "author": (c.get("author") or {}).get("login")}
            for c in self._paged(f"/repos/{full_name}/pulls/{number}/commits", 100)
        ]
        review_comments: list[dict] = []
        issue_comments: list[dict] = []
        if with_discussion:
            review_comments = [
                {"path": c.get("path"), "line": c.get("line") or c.get("original_line"),
                 "author": (c.get("user") or {}).get("login"), "body": c["body"][:1500]}
                for c in self._paged(f"/repos/{full_name}/pulls/{number}/comments", 100)
            ]
            issue_comments = [
                {"author": (c.get("user") or {}).get("login"), "body": c["body"][:1500]}
                for c in self._paged(f"/repos/{full_name}/issues/{number}/comments", 50)
            ]
        return PRInfo(
            repo=full_name, number=number, title=d["title"], body=(d.get("body") or "")[:6000],
            author=(d.get("user") or {}).get("login") or "", state=d["state"],
            merged=bool(d.get("merged")), base_ref=d["base"]["ref"], base_sha=d["base"]["sha"],
            head_ref=d["head"]["ref"], head_sha=d["head"]["sha"],
            additions=d["additions"], deletions=d["deletions"],
            changed_files=d["changed_files"], commits=commits, files=files,
            review_comments=review_comments, issue_comments=issue_comments,
            url=d["html_url"],
        )

    def rate_limit(self) -> dict:
        return self._get("/rate_limit").json()["resources"]["core"]
