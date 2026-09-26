"""Provider-agnostic model client (ADR 0009).

Providers and role assignments come from a JSON file outside the repository
(`REVPR_PROVIDERS`). Three provider types are supported:

- `anthropic`: Messages API over HTTPS, key from an env var.
- `openai`: any OpenAI-compatible chat completions endpoint.
- `command`: a local inference runtime invoked as a subprocess; the prompt is written to stdin
  and the reply read from stdout (plain text or a JSON envelope with a `result` field).

Every call is traced as an OpenInference LLM span.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from ..config import settings
from ..tracing import span

_sema = threading.BoundedSemaphore(int(os.environ.get("REVPR_LLM_CONCURRENCY", "2")))


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    latency_ms: int
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None


def _load_config() -> dict:
    path = settings.providers_file
    if not os.path.isfile(path):
        raise LLMError(f"no provider config at {path}")
    with open(path) as fh:
        return json.load(fh)


_config: dict | None = None


def config() -> dict:
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def role_label(role: str) -> str:
    cfg = config()
    pid = cfg["roles"].get(role, cfg["roles"].get("default"))
    return cfg["providers"][pid].get("label", pid)


# -- provider implementations ------------------------------------------------------------

def _anthropic(p: dict, system: str, prompt: str, schema: dict | None) -> LLMResult:
    key = os.environ.get(p.get("api_key_env", "ANTHROPIC_API_KEY"), "")
    t0 = time.monotonic()
    r = httpx.post(
        p.get("base_url", "https://api.anthropic.com") + "/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": p["model"], "max_tokens": p.get("max_tokens", 8000), "system": system,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=p.get("timeout", 240))
    if r.status_code >= 400:
        raise LLMError(f"provider HTTP {r.status_code}: {r.text[:300]}")
    d = r.json()
    text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    u = d.get("usage", {})
    return LLMResult(text, p["model"], int((time.monotonic() - t0) * 1000),
                     u.get("input_tokens"), u.get("output_tokens"))


def _openai(p: dict, system: str, prompt: str, schema: dict | None) -> LLMResult:
    key = os.environ.get(p.get("api_key_env", "OPENAI_API_KEY"), "")
    body: dict[str, Any] = {"model": p["model"], "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if schema and p.get("json_schema", True):
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "result", "schema": schema, "strict": False}}
    t0 = time.monotonic()
    r = httpx.post(p.get("base_url", "https://api.openai.com/v1") + "/chat/completions",
                   headers={"Authorization": f"Bearer {key}"}, json=body,
                   timeout=p.get("timeout", 240))
    if r.status_code >= 400:
        raise LLMError(f"provider HTTP {r.status_code}: {r.text[:300]}")
    d = r.json()
    u = d.get("usage", {})
    return LLMResult(d["choices"][0]["message"]["content"], p["model"],
                     int((time.monotonic() - t0) * 1000),
                     u.get("prompt_tokens"), u.get("completion_tokens"))


def _command(p: dict, system: str, prompt: str, schema: dict | None) -> LLMResult:
    if p.get("system_in_prompt"):
        prompt = f"{system}\n\n{prompt}"
    with tempfile.TemporaryDirectory() as td:
        schema_path = os.path.join(td, "schema.json")
        out_path = os.path.join(td, "out.txt")
        if schema is not None:
            with open(schema_path, "w") as fh:
                json.dump(schema, fh)
        subst = {"{system}": system, "{schema_file}": schema_path, "{out_file}": out_path,
                 "{model}": p.get("model", ""),
                 "{schema_json}": json.dumps(schema) if schema is not None else ""}
        argv: list[str] = []
        for a in p["argv"]:
            if a in ("{schema_file}", "{schema_json}") and schema is None:
                # drop the flag preceding a schema placeholder when no schema is given
                if argv:
                    argv.pop()
                continue
            for k, v in subst.items():
                a = a.replace(k, v)
            argv.append(a)
        env = dict(os.environ, NO_COLOR="1")
        t0 = time.monotonic()
        try:
            proc = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                                  timeout=p.get("timeout", 300), env=env,
                                  cwd=p.get("cwd", td))
        except subprocess.TimeoutExpired as e:
            raise LLMError("inference timed out") from e
        ms = int((time.monotonic() - t0) * 1000)
        out = proc.stdout
        if os.path.exists(out_path):
            with open(out_path) as fh:
                out = fh.read() or out
    if p.get("parse") == "json_result":
        try:
            d = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"unparseable runtime output: {(proc.stderr or proc.stdout)[:300]}") \
                from e
        if d.get("is_error"):
            raise LLMError(str(d.get("result"))[:300])
        text = d.get("result", "")
        if isinstance(d.get("structured_output"), (dict, list)):
            text = json.dumps(d["structured_output"])
        u = d.get("usage") or {}
        tin = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                          "cache_read_input_tokens")) or None
        return LLMResult(text, p.get("model", ""), ms, tin,
                         u.get("output_tokens"), d.get("total_cost_usd"))
    if proc.returncode != 0 and not out.strip():
        raise LLMError(f"runtime exited {proc.returncode}: {proc.stderr[:300]}")
    return LLMResult(out.strip(), p.get("model", ""), ms)


_IMPL: dict[str, Callable[[dict, str, str, dict | None], LLMResult]] = {
    "anthropic": _anthropic, "openai": _openai, "command": _command,
}


# -- public API ---------------------------------------------------------------------------

def complete(role: str, system: str, prompt: str, schema: dict | None = None) -> LLMResult:
    cfg = config()
    pid = cfg["roles"].get(role, cfg["roles"].get("default"))
    p = cfg["providers"][pid]
    with span(f"llm.{role}", "LLM", input=prompt[-6000:]) as s:
        s.set("llm.model_name", p.get("label", pid))
        s.set("llm.provider", p.get("vendor", "unknown"))
        s.set("llm.system", system[:2000])
        with _sema:
            res = _IMPL[p["type"]](p, system, prompt, schema)
        s.output(res.text[:8000])
        if res.tokens_in is not None:
            s.set("llm.token_count.prompt", res.tokens_in)
        if res.tokens_out is not None:
            s.set("llm.token_count.completion", res.tokens_out)
        if res.cost_usd is not None:
            s.set("llm.cost_usd", res.cost_usd)
        s.set("latency_ms", res.latency_ms)
    return res


def extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("no JSON object in model output")
    return json.loads(text[start:end + 1])


def complete_json(role: str, system: str, prompt: str, schema: dict,
                  validate: Callable[[Any], Any] | None = None) -> tuple[Any, LLMResult]:
    """Call a model for a JSON object; retry once with the validation error appended."""
    last_err = ""
    prompt = (f"{prompt}\n\nReply with a single JSON object that validates against this JSON "
              f"schema. No prose before or after it.\n{json.dumps(schema)}")
    for attempt in range(2):
        p = prompt if attempt == 0 else (
            prompt + f"\n\nYour previous reply was invalid: {last_err}\n"
                     "Reply again with one JSON object that matches the schema.")
        res = complete(role, system, p, schema)
        try:
            obj = extract_json(res.text)
            return (validate(obj) if validate else obj), res
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:300]
    raise LLMError(f"invalid JSON after retry: {last_err}")
