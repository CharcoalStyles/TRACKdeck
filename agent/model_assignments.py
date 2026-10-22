"""
agent/model_assignments.py
---------------------------
Which LM Studio model handles each "surface" (mode) of the app: the model
that does the tool calling, and the model that writes the reply the user
reads. Blank override = the global default (settings.lmstudio_chat_model for
tools, settings.lmstudio_writer_model for replies).

A reply override of NO_WRITER means "no separate writer here" — the tool
model's own text stands (digest/check-ins then use the chat model).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from agent.settings import settings

NO_WRITER = "@tool"

# Modes whose final reply is always handed to the writer (agent/writer.py).
ALWAYS_WRITER = ("onboarding", "profile_chat", "day_planning", "project_chat", "agent_run")


@dataclass(frozen=True)
class Surface:
    key: str
    label: str
    tool_calls: bool
    reply_rule: str


SURFACES: tuple[Surface, ...] = (
    Surface("chat", "Chat (dashboard / default)", True,
            "Tool model for short confirmations. Writer when no tool ran (conversation), the draft is long, "
            "a tool failed, or a schedule / reflection / web-page tool ran."),
    Surface("one_shot", "Voice (one-shot)", True,
            "Tool model, kept short for a push notification. Writer only when a tool failed or a "
            "schedule / reflection / web-page tool ran."),
    Surface("onboarding", "Onboarding interview", True, "Always the writer."),
    Surface("profile_chat", "Profile chat", True, "Always the writer."),
    Surface("day_planning", "Day planning", True, "Always the writer."),
    Surface("project_chat", "Project chat", True, "Always the writer."),
    Surface("agent_run", "Project agent run", True,
            "Always the writer, which also composes long note bodies."),
    Surface("digest", "Daily digest", False, "Always the writer."),
    Surface("checkin", "Check-in prompts", False, "Always the writer (rewording and picking prompts)."),
)
SURFACE_KEYS = {s.key for s in SURFACES}
TOOL_SURFACE_KEYS = {s.key for s in SURFACES if s.tool_calls}


def surface_key(mode: str | None, one_shot: bool, agent_run: bool) -> str:
    if agent_run:
        return "agent_run"
    if mode in ALWAYS_WRITER:
        return mode  # type: ignore[return-value]
    return "one_shot" if one_shot else "chat"


def validate(raw: object) -> dict[str, dict[str, str]]:
    """Normalise a client-supplied overrides dict, raising ValueError on anything unknown."""
    if not isinstance(raw, dict):
        raise ValueError("model_assignments must be an object")
    out: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if key not in SURFACE_KEYS:
            raise ValueError(f"unknown mode {key!r}")
        if not isinstance(value, dict):
            raise ValueError(f"{key}: expected an object with 'tool' and/or 'writer'")
        entry: dict[str, str] = {}
        for role, model in value.items():
            if role not in ("tool", "writer"):
                raise ValueError(f"{key}: unknown role {role!r}")
            if role == "tool" and key not in TOOL_SURFACE_KEYS:
                raise ValueError(f"{key} does no tool calling")
            if not isinstance(model, str):
                raise ValueError(f"{key}.{role}: model id must be a string")
            model = model.strip()
            if model == NO_WRITER and role != "writer":
                raise ValueError(f"{key}.{role}: {NO_WRITER!r} only applies to the writer")
            if model:
                entry[role] = model
        if entry:
            out[key] = entry
    return out


def overrides() -> dict[str, dict[str, str]]:
    try:
        return validate(json.loads(settings.model_assignments or "{}"))
    except (ValueError, TypeError):
        return {}


def tool_model(surface: str | None = None) -> str:
    return overrides().get(surface or "", {}).get("tool") or settings.lmstudio_chat_model


def writer_model(surface: str | None = None) -> str:
    """Model that writes this surface's replies, or "" when no separate writer applies."""
    override = overrides().get(surface or "", {}).get("writer", "")
    if override == NO_WRITER:
        return ""
    return override or settings.lmstudio_writer_model


def matrix() -> dict:
    """Effective assignment for every surface, for the dashboard."""
    ov = overrides()
    rows = []
    for s in SURFACES:
        entry = ov.get(s.key, {})
        t_override = entry.get("tool", "")
        w_override = entry.get("writer", "")
        t_model = t_override or settings.lmstudio_chat_model
        w_model = writer_model(s.key)
        rows.append({
            "key": s.key,
            "label": s.label,
            "tool_calls": s.tool_calls,
            "reply_rule": s.reply_rule,
            "tool_model": t_model if s.tool_calls else None,
            "tool_override": t_override,
            "writer_model": w_model or None,
            "writer_override": w_override,
            "reply_model": w_model or t_model,
        })
    return {
        "provider": settings.llm_provider,
        "split_applies": settings.llm_provider == "lmstudio",
        "default_tool_model": settings.lmstudio_chat_model,
        "default_writer_model": settings.lmstudio_writer_model,
        "no_writer_value": NO_WRITER,
        "rows": rows,
    }
