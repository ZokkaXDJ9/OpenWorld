"""Explicit test-only OpenAI-compatible endpoint for browser smoke tests."""

import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI(title="OpenWorld TEST provider - not an LLM")
requests: list[dict] = []


@app.get("/requests")
def captured_requests():
    return requests


@app.post("/v1/chat/completions")
async def completion(body: dict):
    requests.append(body)
    context = "\n".join(message["content"] for message in body["messages"])
    answer = (
        "Du hast mir erzaehlt, dass Power einen Kristall gefunden hat. "
        "Das weiss ich nur aus deiner Aussage."
        if "Power hat einen Kristall gefunden." in context
        else "Hallo, ich bin Lumia in Glade. Von einem Kristall weiss ich nichts."
    )

    async def stream():
        for word in answer.split(" "):
            yield "data: " + json.dumps({"choices": [{"delta": {"content": word + " "}}]}) + "\n\n"
            await asyncio.sleep(0.02)
        yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
