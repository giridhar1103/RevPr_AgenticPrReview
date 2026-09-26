"""OpenTelemetry tracing with OpenInference conventions, exported to Phoenix (ADR 0011).

Spans are also mirrored into an in-memory trace list per job so the UI can show the retrieval
trace without querying Phoenix.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .config import settings

log = logging.getLogger(__name__)

KIND = "openinference.span.kind"
INPUT = "input.value"
OUTPUT = "output.value"

_tracer = None
_job_trace: ContextVar[list | None] = ContextVar("job_trace", default=None)


def init(project: str = "revpr") -> None:
    global _tracer
    if _tracer is not None:
        return
    try:
        from phoenix.otel import register
        provider = register(project_name=project, endpoint=settings.phoenix_endpoint,
                            batch=True, set_global_tracer_provider=True, verbose=False)
        _tracer = provider.get_tracer("revpr")
    except Exception as e:  # noqa: BLE001
        log.warning("tracing disabled: %s", e)
        _tracer = trace.get_tracer("revpr")


def tracer():
    if _tracer is None:
        init()
    return _tracer


@contextmanager
def job_trace() -> Iterator[list]:
    steps: list = []
    token = _job_trace.set(steps)
    try:
        yield steps
    finally:
        _job_trace.reset(token)


def _clip(value: Any, n: int = 4000) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    return s if len(s) <= n else s[:n] + "...[truncated]"


class Step:
    """Handle yielded by `span`; records attributes on the OTel span and the job trace."""

    def __init__(self, otel_span, record: dict):
        self.otel = otel_span
        self.record = record

    def set(self, key: str, value: Any) -> None:
        if isinstance(value, (str, int, float, bool)):
            self.otel.set_attribute(key, value)
        else:
            self.otel.set_attribute(key, _clip(value))
        self.record.setdefault("attrs", {})[key] = value

    def output(self, value: Any) -> None:
        self.otel.set_attribute(OUTPUT, _clip(value))
        self.record["output"] = value

    def documents(self, docs: list[dict]) -> None:
        """OpenInference retrieval.documents.* attributes."""
        for i, d in enumerate(docs[:50]):
            p = f"retrieval.documents.{i}.document"
            self.otel.set_attribute(f"{p}.id", str(d.get("id")))
            self.otel.set_attribute(f"{p}.score", float(d.get("score") or 0))
            self.otel.set_attribute(f"{p}.content", _clip(d.get("content", ""), 1500))
            meta = {k: v for k, v in d.items() if k not in ("id", "score", "content")}
            self.otel.set_attribute(f"{p}.metadata", _clip(meta, 500))
        self.record["documents"] = [
            {k: v for k, v in d.items() if k != "content"} for d in docs[:50]]


@contextmanager
def span(name: str, kind: str = "CHAIN", input: Any = None, **attrs: Any) -> Iterator[Step]:
    record: dict = {"name": name, "kind": kind, "start": time.time()}
    if input is not None:
        record["input"] = input
    parent = _job_trace.get()
    with tracer().start_as_current_span(name) as s:
        s.set_attribute(KIND, kind)
        if input is not None:
            s.set_attribute(INPUT, _clip(input))
        step = Step(s, record)
        for k, v in attrs.items():
            step.set(k, v)
        try:
            yield step
        except Exception as e:
            s.set_status(Status(StatusCode.ERROR, str(e)[:200]))
            record["error"] = str(e)[:300]
            raise
        finally:
            record["ms"] = int((time.time() - record["start"]) * 1000)
            if parent is not None:
                parent.append(record)
