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


@app.get("/v1/models")
def models():
    return {"data": [{"id": "mock-model"}]}


@app.get("/api/v1/models")
def lmstudio_models():
    return {
        "models": [
            {
                "type": "llm",
                "key": "mock-model",
                "display_name": "Testmodell",
                "loaded_instances": [{"id": "mock-model", "config": {"context_length": 16384}}],
                "capabilities": {"reasoning": {"allowed_options": ["off", "on"]}},
            }
        ]
    }


@app.get("/api/tags")
@app.get("/api/ps")
def ollama_models():
    return {"models": [{"name": "mock-model", "context_length": 8192}]}


@app.post("/api/show")
def ollama_metadata():
    return {"capabilities": ["completion", "thinking"]}


@app.post("/api/chat")
def ollama_completion(body: dict):
    requests.append(body)
    if not body.get("stream"):
        return {"message": {"content": '{"events":[]}'}, "done": True}

    async def stream():
        yield json.dumps({"message": {"content": "Verbindung funktioniert."}, "done": True}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/v1/chat/completions")
async def completion(body: dict):
    requests.append(body)
    if not body.get("stream"):
        source = json.loads(body["messages"][1]["content"])
        message = source["source"]
        events = []
        if message["role"] == "user" and message["content"].startswith("Power hat "):
            events.append(
                {
                    "event_type": "knowledge_acquired",
                    "description": "Bericht über Power",
                    "confidence": 90,
                    "evidence_quote": message["content"],
                    "operations": [
                        {
                            "op": "knowledge",
                            "character_id": source["recipient_id"],
                            "kind": "received",
                            "confidence": 50,
                            "content": message["content"],
                        }
                    ],
                }
            )
        return {"choices": [{"message": {"content": json.dumps({"events": events})}}]}
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
