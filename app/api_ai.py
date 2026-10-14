"""Ask AI routes: stream an LLM answer about one post or Short."""

from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import ai
from app.config import Settings
from app.deps import admin_user, current_user, get_db, get_settings

router = APIRouter()

# Only fetch the linked page when the feed itself gives little text.
ARTICLE_WHEN_TEXT_BELOW = 2000


class AskBody(BaseModel):
    type: Literal["item", "short"]
    id: int
    mode: Literal["summary", "factcheck", "explain", "question"] = "summary"
    question: str = Field(default="", max_length=1000)


@router.post("/api/ai/ask")
async def ask(
    body: AskBody,
    user=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    s: Settings = Depends(get_settings),
):
    """Stream the answer as plain text. Errors before the first word are HTTP errors; later ones are appended."""
    if not ai.configured(s):
        raise HTTPException(503, "No AI server is configured. An admin can set LLM_BASE_URL and LLM_MODEL.")
    if body.mode == "question" and not body.question.strip():
        raise HTTPException(400, "Type a question first")
    ctx = await run_in_threadpool(ai.item_context, conn, s, body.type, body.id)
    if ctx is None:
        raise HTTPException(404, "Not found")
    article = ""
    if s.llm_fetch_article and body.type == "item" and ctx["url"] and len(ctx["text"]) < ARTICLE_WHEN_TEXT_BELOW:
        article = await run_in_threadpool(ai.article_text, ctx["url"], s, s.llm_max_context_chars)
    messages = ai.build_messages(ctx, body.mode, body.question, s, article)

    stream = ai.stream_chat(s, messages).__aiter__()
    try:
        first = await stream.__anext__()
    except StopAsyncIteration:
        first = "(The model returned an empty answer.)"
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from None

    async def body_iter():
        yield first
        try:
            async for chunk in stream:
                yield chunk
        except ai.AIError as exc:
            yield f"\n\n[AI error: {exc}]"

    return StreamingResponse(
        body_iter(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "X-AI-Model": s.llm_model,
            "X-AI-Article": "1" if article else "0",
        },
    )


@router.post("/api/admin/ai/test")
async def test_connection(user=Depends(admin_user), s: Settings = Depends(get_settings)):
    if not ai.configured(s):
        return {"ok": False, "error": "LLM_BASE_URL and LLM_MODEL are not set", "models": []}
    try:
        models = await run_in_threadpool(ai.list_models, s)
    except ai.AIError as exc:
        return {"ok": False, "error": str(exc), "models": []}
    found = s.llm_model in models or f"{s.llm_model}:latest" in models  # Ollama's default tag
    return {
        "ok": found,
        "error": None if found else f"Model {s.llm_model!r} is not on the server. Available: {', '.join(models)[:300]}",
        "models": models[:50],
    }
