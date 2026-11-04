"""Opt-in real local-model acceptance. Uses only synthetic data and a disposable database."""

import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="openworld-local-test")
    parser.add_argument("--port", type=int, default=1234)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"model": args.model, "checks": {}, "trace": []}
    report["source_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    report["source_dirty"] = bool(
        subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    )
    with TemporaryDirectory(prefix="openworld-live-simulation-") as directory:
        os.environ["OPENWORLD_DATA_DIR"] = directory
        os.environ.pop("OPENWORLD_DATABASE_URL", None)
        subprocess.run(
            [os.sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).parents[1],
            check=True,
            capture_output=True,
        )
        from fastapi.testclient import TestClient
        from sqlalchemy import select

        from app.context import build_context
        from app.db import SessionLocal, engine, get_db
        from app.main import app
        from app.models import Conversation, Knowledge, Simulation
        from app.provider import OpenAIProvider
        from app.simulation import step

        class TraceProvider:
            def __init__(self):
                self.provider = OpenAIProvider()

            async def stream(self, messages, settings):
                entry = {"kind": "chat", "messages": messages, "output": ""}
                report["trace"].append(entry)
                async for part in self.provider.stream(messages, settings):
                    entry["output"] += part
                    yield part

            async def extract(self, messages, settings):
                entry = {"kind": "extraction", "messages": messages}
                report["trace"].append(entry)
                response = await self.provider.extract(messages, settings)
                entry.update(output=response.content, diagnostics=response.diagnostics)
                return response

        def database():
            with SessionLocal() as db:
                yield db

        app.dependency_overrides[get_db] = database
        provider = TraceProvider()
        app.state.provider = provider
        try:
            with TestClient(app) as client:

                def post(path, body):
                    response = client.post("/api" + path, json=body)
                    response.raise_for_status()
                    return response.json()

                client.put(
                    "/api/settings/provider",
                    json={
                        "base_url": f"http://127.0.0.1:{args.port}/v1",
                        "model": args.model,
                        "context_window": 16384,
                        "max_output_tokens": 384,
                        "temperature": 0.1,
                        "reasoning_profile": "lmstudio",
                        "reasoning_mode": "off",
                    },
                ).raise_for_status()
                client.put(
                    "/api/settings/extraction",
                    json={
                        "provider_profile": "lmstudio",
                        "reasoning_mode": "off",
                        "context_window": 16384,
                        "max_output_tokens": 4096,
                        "structured_output": "text",
                        "auto_retry": False,
                    },
                ).raise_for_status()
                world = post("/worlds", {"name": "Synthetischer Mehrcharaktertest"})
                path = f"/worlds/{world['id']}"
                location = post(path + "/locations", {"name": "Testgarten"})
                power = post(
                    path + "/characters",
                    {
                        "name": "Power",
                        "location_id": location["id"],
                        "travel_status": "present",
                        "profile": {
                            "Aufgabe": "Beginne das Gespräch. Erzähle Lumia in einem kurzen Satz "
                            "die Kristallfarbe. Nur gesprochener Text, keine Handlungen.",
                            "Geheimnis": "POWER-PRIVAT-478",
                        },
                    },
                )
                lumia = post(
                    path + "/characters",
                    {
                        "name": "Lumia",
                        "location_id": location["id"],
                        "travel_status": "present",
                        "profile": {
                            "Aufgabe": "Antworte kurz auf Powers tatsächliche Aussage.",
                            "Geheimnis": "LUMIA-PRIVAT-931",
                        },
                    },
                )
                post(
                    path + "/knowledge",
                    {
                        "character_id": power["id"],
                        "kind": "knowledge",
                        "content": "Mein Kristall ist violett.",
                        "confidence": 100,
                    },
                )
                post(
                    path + "/knowledge",
                    {
                        "kind": "fact",
                        "public": False,
                        "content": "WELT-VERBORGEN-682",
                    },
                )
                simulation = post(
                    path + "/simulations",
                    {
                        "character_ids": [power["id"], lumia["id"]],
                        "location_id": location["id"],
                        "max_rounds": 2,
                        "max_calls": 12,
                        "max_tokens": 100000,
                        "timeout_seconds": 600,
                    },
                )
                post(
                    path + f"/simulations/{simulation['id']}/control/start",
                    {"revision": simulation["revision"]},
                )

                async def exercise():
                    with SessionLocal() as db:
                        await step(db, simulation["id"], provider)
                        await step(db, simulation["id"], provider)

                asyncio.run(exercise())
                result = client.get("/api" + path + f"/simulations/{simulation['id']}").json()
                report["simulation"] = result
                checks = report["checks"]
                checks["two_autonomous_turns"] = (
                    result["status"] == "completed"
                    and result["completed_rounds"] == 2
                    and [row["speaker_character_id"] for row in result["messages"]]
                    == [power["id"], lumia["id"]]
                )
                chats = [row for row in report["trace"] if row["kind"] == "chat"]
                checks["isolated_private_profiles"] = len(chats) == 2 and (
                    "LUMIA-PRIVAT-931" not in json.dumps(chats[0]["messages"])
                    and "POWER-PRIVAT-478" not in json.dumps(chats[1]["messages"])
                )
                checks["hidden_world_fact_excluded"] = all(
                    "WELT-VERBORGEN-682" not in json.dumps(row["messages"])
                    for row in report["trace"]
                )
                with SessionLocal() as db:
                    learned = list(
                        db.scalars(
                            select(Knowledge).where(
                                Knowledge.character_id == lumia["id"],
                                Knowledge.origin == "event",
                            )
                        )
                    )
                    report["learned"] = [
                        {
                            "kind": row.kind,
                            "content": row.content,
                            "confidence": row.confidence,
                            "event_id": row.event_id,
                        }
                        for row in learned
                    ]
                    checks["personal_received_memory"] = any(
                        row.kind == "received"
                        and row.confidence <= 50
                        and "violett" in row.content.casefold()
                        for row in learned
                    )
                    report["persisted_status"] = db.get(Simulation, simulation["id"]).status
                conversation = post(
                    path + "/conversations",
                    {
                        "character_id": lumia["id"],
                        "title": "Späterer Erinnerungsabruf",
                    },
                )
                with SessionLocal() as db:
                    context, _ = build_context(
                        db, db.get(Conversation, conversation["id"]), 16384, 384
                    )
                    checks["new_conversation_has_memory"] = (
                        "violett" in json.dumps(context).casefold()
                    )
                recall = client.post(
                    f"/api/conversations/{conversation['id']}/messages",
                    json={
                        "content": "Welche Farbe hat Powers Kristall?",
                    },
                )
                recall.raise_for_status()
                report["recall"] = recall.text
                checks["real_model_recall"] = "violett" in recall.text.casefold()
                checks["no_private_profile_leak_in_public_text"] = all(
                    "PRIVAT-" not in row["content"] for row in result["messages"]
                )
                checks["world_clock"] = result["clock"]["elapsed_minutes"] == 2
                extractions = [row for row in report["trace"] if row["kind"] == "extraction"]
                checks["no_reasoning_during_extraction"] = bool(extractions) and all(
                    row.get("diagnostics", {}).get("reasoning_tokens") == 0
                    for row in extractions
                )
        finally:
            app.dependency_overrides.clear()
            engine.dispose()
    report["checks"]["temporary_database_removed"] = not Path(directory).exists()
    report["passed"] = all(report["checks"].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": report["checks"]}, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
