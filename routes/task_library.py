"""
routes/task_library.py
-------------------------
Plain CRUD for the Day Planning page's reusable task library — see
utils/task_library_store.py.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

import auth
from utils import task_library_store
from utils.planning import parse_order_hint

router = APIRouter()


class TaskLibraryItem(BaseModel):
    id: str
    label: str
    default_minutes: int
    group_name: Optional[str] = None
    order_hint: Optional[str] = None


class TaskLibraryInput(BaseModel):
    label: str
    default_minutes: int
    group_name: Optional[str] = None
    order_hint: Optional[str] = None

    @field_validator("order_hint")
    @classmethod
    def _valid_order_hint(cls, value: Optional[str]) -> Optional[str]:
        value = (value or "").strip()
        if not value:
            return None
        if parse_order_hint(value) is None:
            raise ValueError('order_hint must read "before <task>" or "after <task>"')
        return value


@router.get("/task-library", response_model=list[TaskLibraryItem])
async def list_task_library(_: Annotated[None, Depends(auth.require_session_or_token)]):
    return await asyncio.to_thread(task_library_store.list_all)


@router.post("/task-library", response_model=TaskLibraryItem)
async def create_task_library_item(
    body: TaskLibraryInput, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    item_id = str(uuid.uuid4())
    await asyncio.to_thread(
        task_library_store.create,
        item_id,
        body.label,
        body.default_minutes,
        body.group_name,
        body.order_hint,
    )
    return await asyncio.to_thread(task_library_store.get, item_id)


@router.put("/task-library/{item_id}", response_model=TaskLibraryItem)
async def update_task_library_item(
    item_id: str, body: TaskLibraryInput, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    if await asyncio.to_thread(task_library_store.get, item_id) is None:
        raise HTTPException(status_code=404, detail="Task library item not found")
    return await asyncio.to_thread(
        task_library_store.update,
        item_id,
        body.label,
        body.default_minutes,
        body.group_name,
        body.order_hint,
    )


@router.delete("/task-library/{item_id}")
async def delete_task_library_item(
    item_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    if await asyncio.to_thread(task_library_store.get, item_id) is None:
        raise HTTPException(status_code=404, detail="Task library item not found")
    await asyncio.to_thread(task_library_store.delete, item_id)
    return {"status": "deleted"}
