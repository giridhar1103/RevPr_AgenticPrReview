"""Hardened git operations on untrusted public repositories.

Every command runs with hooks, submodules, symlinks, local and ext transports, credential
helpers and global config disabled (ADR 0010). Clones are blobless partial clones, so history
is available without downloading every file version.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings

_SAFE_CONFIG = [
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.symlinks=false",
    "-c", "core.fsmonitor=false",
    "-c", "protocol.file.allow=never",
    "-c", "protocol.ext.allow=never",
    "-c", "submodule.recurse=false",
    "-c", "credential.helper=",
    "-c", "diff.renames=false",
    "-c", "advice.detachedHead=false",
    "-c", "gc.auto=0",
]

_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_LFS_SKIP_SMUDGE": "1",
    "GIT_ASKPASS": "/bin/false",
    "PATH": "/usr/bin:/bin",
    "HOME": "/nonexistent",
    "LC_ALL": "C",
}


class GitError(Exception):
    pass


def git(args: list[str], cwd: Path | None = None, timeout: int = 120,
        check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *_SAFE_CONFIG, *args], cwd=cwd, env=_ENV, capture_output=True,
        timeout=timeout, text=True, errors="replace",
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {args[0]} failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def repo_dir(full_name: str) -> Path:
    owner, name = full_name.split("/", 1)
    return settings.repos_dir / f"{owner}__{name}"


@contextmanager
def repo_lock(full_name: str) -> Iterator[None]:
    """Serialize working-tree changes per repository across processes."""
    lock_path = settings.repos_dir / f".{full_name.replace('/', '__')}.lock"
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def ensure_clone(full_name: str) -> Path:
    d = repo_dir(full_name)
    url = f"https://github.com/{full_name}.git"
    if (d / ".git").is_dir():
        return d
    if d.exists():
        shutil.rmtree(d)
    git(["clone", "--filter=blob:none", "--no-checkout", "--no-recurse-submodules",
         "--quiet", url, str(d)], timeout=settings.clone_timeout_s)
    return d


def fetch_commit(d: Path, ref: str) -> None:
    """Make sure a commit (or pull/N/head ref) is present locally."""
    if ref and len(ref) == 40:
        ok = subprocess.run(["git", *_SAFE_CONFIG, "cat-file", "-e", f"{ref}^{{commit}}"],
                            cwd=d, env=_ENV, capture_output=True).returncode == 0
        if ok:
            return
    git(["fetch", "--filter=blob:none", "--no-recurse-submodules", "--quiet", "origin", ref],
        cwd=d, timeout=settings.clone_timeout_s)


def checkout(d: Path, sha: str) -> None:
    fetch_commit(d, sha)
    git(["checkout", "--quiet", "--force", "--detach", sha], cwd=d,
        timeout=settings.clone_timeout_s)
    # A forced checkout leaves untracked files from other commits behind; clean them.
    git(["clean", "-fdxq"], cwd=d, timeout=60)


def show_file(d: Path, sha: str, path: str, max_bytes: int = 400_000) -> str | None:
    proc = subprocess.run(["git", *_SAFE_CONFIG, "show", f"{sha}:{path}"], cwd=d, env=_ENV,
                          capture_output=True, timeout=60)
    if proc.returncode != 0 or len(proc.stdout) > max_bytes or b"\0" in proc.stdout[:8000]:
        return None
    return proc.stdout.decode("utf-8", "replace")


def log_names(d: Path, sha: str, limit: int) -> list[tuple[str, str, int, list[str]]]:
    """(sha, author, unix time, files) for the last `limit` non-merge commits at `sha`."""
    out = git(["log", "--no-merges", "--no-renames", f"-n{limit}",
               "--format=%x1e%H%x1f%an%x1f%at", "--name-only", sha], cwd=d, timeout=120)
    commits = []
    for block in out.split("\x1e"):
        block = block.strip("\n")
        if not block:
            continue
        head, _, rest = block.partition("\n")
        parts = head.split("\x1f")
        if len(parts) != 3:
            continue
        files = [f for f in rest.splitlines() if f.strip()]
        commits.append((parts[0], parts[1], int(parts[2]), files))
    return commits


def file_log(d: Path, sha: str, path: str, limit: int = 8) -> list[dict]:
    out = git(["log", "--no-merges", "--no-renames", f"-n{limit}",
               "--format=%H%x1f%an%x1f%at%x1f%s", sha, "--", path], cwd=d, timeout=60,
              check=False)
    rows = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            rows.append({"sha": parts[0][:10], "author": parts[1], "time": int(parts[2]),
                         "subject": parts[3][:160]})
    return rows


def iter_source_files(root: Path) -> Iterator[tuple[str, Path]]:
    excluded = set(settings.excluded_dirs)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [x for x in dirnames if x not in excluded and not x.startswith(".")]
        for fn in filenames:
            full = Path(dirpath) / fn
            if full.is_symlink():
                continue
            rel = str(full.relative_to(root))
            yield rel, full


def read_text(full: Path) -> bytes | None:
    try:
        size = full.stat().st_size
    except OSError:
        return None
    if size == 0 or size > settings.max_file_bytes:
        return None
    data = full.read_bytes()
    if b"\0" in data[:8000]:
        return None
    lines = data.count(b"\n") + 1
    if len(data) / lines > 400:  # minified or generated
        return None
    return data
