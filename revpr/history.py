"""Behavioral signals from git history: churn, authorship and co-change (ADR 0007)."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import gitops
from .config import settings

RECENT_S = 90 * 86400
MIN_COCHANGE = 2


@dataclass
class HistoryStats:
    churn: Counter
    churn_recent: Counter
    authors: dict[str, set[str]]
    last_commit: dict[str, int]
    cochange: dict[tuple[str, str], int]
    commits: int


def collect(repo: Path, sha: str) -> HistoryStats:
    commits = gitops.log_names(repo, sha, settings.history_commits)
    churn: Counter = Counter()
    recent: Counter = Counter()
    authors: dict[str, set[str]] = defaultdict(set)
    last: dict[str, int] = {}
    pairs: Counter = Counter()
    newest = commits[0][2] if commits else int(time.time())
    for _, author, ts, files in commits:
        for f in files:
            churn[f] += 1
            authors[f].add(author)
            last.setdefault(f, ts)
            if newest - ts <= RECENT_S:
                recent[f] += 1
        # Large commits (formatting, vendoring, renames) say little about coupling.
        if 1 < len(files) <= settings.cochange_max_files:
            fs = sorted(set(files))
            for i in range(len(fs)):
                for j in range(i + 1, len(fs)):
                    pairs[(fs[i], fs[j])] += 1
    cochange = {k: v for k, v in pairs.items() if v >= MIN_COCHANGE}
    return HistoryStats(churn, recent, authors, last, cochange, len(commits))
