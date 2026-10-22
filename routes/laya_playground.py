"""
routes/laya_playground.py
--------------------------
Backend for the dashboard's Laya Playground admin page — a standalone
space to try pydecide's decision model interactively against arbitrary
text before any real integration is built. Not wired into agent/graph.py
or the actual tool-calling path in any way; see utils/laya_client.py's
docstring for why pydecide isn't a project dependency yet and what
"deploying" this for real still requires.

Four question types exposed, matching pydecide's actual API
(utils/laya_client.py) plus one composed on top of it:
  - yes_no          -> Noul (native)
  - choose_one      -> Choice (native)
  - scale           -> Score (native)
  - choose_multiple -> N parallel Noul calls in one request (composed —
                        pydecide has no native multi-select primitive)
  - tool            -> Choice against the live tool registry
                        (agent/tools/all_tools.py), the project's actual
                        motivating use case
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

import auth
from utils.laya_client import (
    LayaNotInstalled,
    ask_choose_multiple,
    ask_choose_one,
    ask_scale,
    ask_tool,
    ask_yes_no,
    get_tool_candidates,
)

router = APIRouter()

_DEFAULT_INSTRUCTIONS = {
    "yes_no": "Does the following apply?",
    "choose_one": "Which of these best matches?",
    "choose_multiple": "Which of these apply?",
    "scale": "Rate this on the given scale.",
    "tool": "Which tool should be called for this request?",
}


class LayaCandidate(BaseModel):
    name: str
    description: str | None = None


class LayaPlaygroundRequest(BaseModel):
    text: str
    question_type: Literal["yes_no", "choose_one", "choose_multiple", "scale", "tool"]
    # Falls back to a sensible per-type default (_DEFAULT_INSTRUCTIONS) if omitted.
    instructions: str | None = None
    # Required for choose_one/choose_multiple/scale; ignored for yes_no/tool
    # (tool auto-populates from the live tool registry).
    candidates: list[LayaCandidate] | None = None
    # Optional Noul true/false label overrides, yes_no only.
    yes_label: str | None = None
    no_label: str | None = None
    # choose_multiple only: per-candidate cutoff for inclusion in `selected`.
    multi_threshold: float = 0.5

    @model_validator(mode="after")
    def _check(self):
        if not self.text.strip():
            raise ValueError("text cannot be blank")
        needs_candidates = self.question_type in ("choose_one", "choose_multiple", "scale")
        if needs_candidates and not self.candidates:
            raise ValueError(f"question_type='{self.question_type}' requires at least one candidate")
        if self.question_type == "scale" and self.candidates and len(self.candidates) < 2:
            raise ValueError("question_type='scale' requires at least two levels (low to high)")
        if not (0.0 <= self.multi_threshold <= 1.0):
            raise ValueError("multi_threshold must be between 0 and 1")
        return self


class LayaAnswerOption(BaseModel):
    name: str
    probability: float


class LayaPlaygroundResponse(BaseModel):
    question_type: str
    choice: str | None = None
    yes_probability: float | None = None
    score: float | None = None
    levels: list[str] | None = None
    selected: list[str] | None = None
    options: list[LayaAnswerOption] | None = None
    backend: str
    model: str | None
    latency_ms: float
    route: list[str]


class LayaToolCandidate(BaseModel):
    name: str
    description: str


@router.get("/laya-playground/tools", response_model=list[LayaToolCandidate])
async def list_laya_tool_candidates(_: Annotated[None, Depends(auth.require_session_or_token)]):
    """The live tool list "tool" mode actually tests against — shown
    read-only in the Playground so it's clear what candidates Laya is
    choosing between, straight from agent/tools/all_tools.py."""
    candidates = get_tool_candidates()
    return [{"name": k, "description": v} for k, v in candidates.items()]


@router.post("/laya-playground/ask", response_model=LayaPlaygroundResponse)
async def ask_laya(request: LayaPlaygroundRequest, _: Annotated[None, Depends(auth.require_session_or_token)]):
    instructions = request.instructions or _DEFAULT_INSTRUCTIONS[request.question_type]
    candidates = {c.name: c.description for c in request.candidates} if request.candidates else {}

    try:
        if request.question_type == "yes_no":
            result = await ask_yes_no(request.text, instructions, request.yes_label, request.no_label)
        elif request.question_type == "choose_one":
            result = await ask_choose_one(request.text, instructions, candidates)
        elif request.question_type == "choose_multiple":
            result = await ask_choose_multiple(request.text, instructions, candidates, request.multi_threshold)
        elif request.question_type == "scale":
            result = await ask_scale(request.text, instructions, [c.name for c in request.candidates])
        else:  # "tool"
            result = await ask_tool(request.text, instructions)
    except LayaNotInstalled as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {"question_type": request.question_type, **result}
