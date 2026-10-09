"""Thin Anthropic wrapper: JSON out, pydantic validation, one retry, then fail loudly."""
from __future__ import annotations

import json
import os
import re
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

try:  # optional .env support
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-sonnet-5-5"


class LLMError(RuntimeError):
    pass


def model_name() -> str:
    return os.environ.get("NOVBE_MODEL", DEFAULT_MODEL)


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


_client = None


def _get_client():
    global _client
    if _client is None:
        if not available():
            raise LLMError("ANTHROPIC_API_KEY is not set")
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def complete(system: str, user: str, max_tokens: int = 4096) -> str:
    """One deterministic text completion (temperature 0)."""
    client = _get_client()
    kwargs = dict(
        model=model_name(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=0,
    )
    try:
        resp = client.messages.create(**kwargs)
    except Exception as e:  # some models reject sampling params; retry without
        if "temperature" in str(e).lower():
            kwargs.pop("temperature")
            resp = client.messages.create(**kwargs)
        else:
            raise
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def extract_json(text: str) -> str:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text.strip()


def complete_json(system: str, user: str, model: type[T], max_tokens: int = 4096) -> tuple[T, dict]:
    """Ask for JSON matching `model`. Validate; on failure retry once with the error, then raise.

    Returns (validated object, meta) where meta has the raw text and elapsed seconds.
    """
    t0 = time.perf_counter()
    raw = complete(system, user, max_tokens)
    try:
        obj = model.model_validate(json.loads(extract_json(raw)))
        return obj, {"raw": raw, "seconds": time.perf_counter() - t0, "retried": False}
    except (json.JSONDecodeError, ValidationError) as err:
        fix = (
            f"{user}\n\nYour previous answer was:\n{raw}\n\nIt failed validation with:\n{err}\n\n"
            "Return ONLY the corrected JSON object."
        )
        raw2 = complete(system, fix, max_tokens)
        try:
            obj = model.model_validate(json.loads(extract_json(raw2)))
        except (json.JSONDecodeError, ValidationError) as err2:
            raise LLMError(f"LLM output failed validation twice: {err2}") from err2
        return obj, {"raw": raw2, "seconds": time.perf_counter() - t0, "retried": True}
