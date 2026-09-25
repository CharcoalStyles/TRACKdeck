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
from pydantic import BaseModel

import auth
from utils import task_library_store

router = APIRouter()


class TaskLibraryItem(BaseModel):
    id: str
    label: str
    default_minutes: int
    group_name: Optional[str] = None


class TaskLibraryInput(BaseModel):
    label: str
    default_minutes: int
    group_name: Optional[str] = None


@router.get("/task-library", response_model=list[TaskLibraryItem])
async def list_task_library(_: Annotated[None, Depends(auth.require_session_or_token)]):
    return await asyncio.to_thread(task_library_store.list_all)


@router.post("/task-library", response_model=TaskLibraryItem)
async def create_task_library_item(
    body: TaskLibraryInput, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    item_id = str(uuid.uuid4())
    await asyncio.to_thread(
        task_library_store.create, item_id, body.label, body.default_minutes, body.group_name
    )
    return await asyncio.to_thread(task_library_store.get, item_id)


@router.put("/task-library/{item_id}", response_model=TaskLibraryItem)
async def update_task_library_item(
    item_id: str, body: TaskLibraryInput, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    if await asyncio.to_thread(task_library_store.get, item_id) is None:
        raise HTTPException(status_code=404, detail="Task library item not found")
    return await asyncio.to_thread(
        task_library_store.update, item_id, body.label, body.default_minutes, body.group_name
    )


@router.delete("/task-library/{item_id}")
async def delete_task_library_item(
    item_id: str, _: Annotated[None, Depends(auth.require_session_or_token)]
):
    if await asyncio.to_thread(task_library_store.get, item_id) is None:
        raise HTTPException(status_code=404, detail="Task library item not found")
    await asyncio.to_thread(task_library_store.delete, item_id)
    return {"status": "deleted"}
