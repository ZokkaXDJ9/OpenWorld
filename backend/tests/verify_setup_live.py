"""Opt-in guided setup acceptance using a real local model and disposable data."""

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
    report = {
        "model": args.model,
        "checks": {},
        "trace": [],
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        ),
    }
    with TemporaryDirectory(prefix="openworld-live-setup-") as directory:
        os.environ["OPENWORLD_DATA_DIR"] = directory
        os.environ.pop("OPENWORLD_DATABASE_URL", None)
        subprocess.run(
            [os.sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).parents[1],
            check=True,
            capture_output=True,
        )
        from fastapi.testclient import TestClient

        from app.db import SessionLocal, engine, get_db
        from app.extraction import run_job
        from app.main import app
        from app.provider import OpenAIProvider
        from app.simulation import step

        class TraceProvider:
            async def stream(self, messages, settings):
                entry = {
                    "kind": "chat",
                    "model": settings.model,
                    "reasoning_mode": settings.reasoning_mode,
                    "output": "",
                    "context": json.dumps(messages, ensure_ascii=False),
                }
                report["trace"].append(entry)
                async for part in OpenAIProvider().stream(messages, settings):
                    entry["output"] += part
                    yield part

            async def extract(self, messages, settings):
                response = await OpenAIProvider().extract(messages, settings)
                report["trace"].append(
                    {
                        "kind": "memory",
                        "model": settings.model,
                        "reasoning_mode": settings.reasoning_mode,
                        "diagnostics": response.diagnostics,
                        "output": response.content,
                        "context": json.dumps(messages, ensure_ascii=False),
                    }
                )
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

                checks = report["checks"]
                checks["first_start_without_connection"] = (
                    client.get("/api/settings/provider/status").json()["state"] == "missing"
                )
                draft = {
                    "base_url": f"http://127.0.0.1:{args.port}/v1",
                    "model": args.model,
                    "kind": "lmstudio",
                    "automatic": True,
                }
                listing = post("/settings/provider/models", draft)
                checks["loaded_model_discovered"] = any(
                    item["id"] == args.model and item["loaded"] for item in listing["details"]
                )
                tested = post("/settings/provider/test", draft)
                report["setup_test"] = tested
                checks["one_real_setup_request"] = tested["attempts"] == 1 and bool(tested["reply"])
                checks["runtime_metadata_used"] = tested["settings"]["context_window"] == 16384
                values = {k: v for k, v in tested["settings"].items() if k != "has_api_key"}
                post(
                    "/settings/setup",
                    {
                        "provider": values,
                        "kind": "lmstudio",
                        "configure_memories": True,
                        "verification_token": tested["verification_token"],
                    },
                )
                checks["saved_connection_ready"] = (
                    client.get("/api/settings/provider/status").json()["state"] == "ready"
                )
                memory = client.get("/api/settings/extraction").json()
                checks["automatic_memory_configuration"] = (
                    memory["use_chat_connection"]
                    and memory["model"] == ""
                    and memory["reasoning_mode"] == "off"
                    and not memory["auto_retry"]
                    and memory["structured_output"] == "text"
                )
                world = post("/worlds", {"name": "Synthetischer Einrichtungstest"})
                path = f"/worlds/{world['id']}"
                location = post(path + "/locations", {"name": "Testgarten"})
                lumia = post(
                    path + "/characters",
                    {
                        "name": "Lumia",
                        "location_id": location["id"],
                        "travel_status": "present",
                        "profile": {"Stil": "Antworte kurz auf Deutsch, höchstens zwei Sätze."},
                    },
                )
                power = post(
                    path + "/characters",
                    {
                        "name": "Power",
                        "location_id": location["id"],
                        "travel_status": "present",
                        "profile": {"Geheimnis": "POWER-PRIVAT-478"},
                    },
                )
                options = client.get("/api" + path + "/event-settings").json()
                client.put(
                    "/api" + path + "/event-settings",
                    json={
                        "enabled": True,
                        "confirm_changes": True,
                        "revision": options["revision"],
                    },
                ).raise_for_status()
                conversation = post(path + "/conversations", {"character_id": lumia["id"]})
                answer = client.post(
                    f"/api/conversations/{conversation['id']}/messages",
                    json={
                        "content": "Power hat einen violetten Kristall gefunden.",
                    },
                )
                answer.raise_for_status()
                checks["normal_character_chat"] = '"error"' not in answer.text
                jobs = client.get("/api" + path + "/extraction-jobs").json()
                for job in jobs:
                    with SessionLocal() as db:
                        asyncio.run(run_job(db, job["id"], provider))
                report["jobs"] = client.get("/api" + path + "/extraction-jobs").json()
                learned = client.get("/api" + path + "/knowledge").json()
                checks["personal_memory_created"] = any(
                    row["character_id"] == lumia["id"]
                    and row["kind"] == "received"
                    and row["confidence"] <= 50
                    and "violett" in row["content"].casefold()
                    for row in learned
                )
                later = post(path + "/conversations", {"character_id": lumia["id"]})
                recalled = client.post(
                    f"/api/conversations/{later['id']}/messages",
                    json={
                        "content": "Welche Farbe hat Powers Kristall?",
                    },
                )
                recalled.raise_for_status()
                checks["new_conversation_recalls_memory"] = "violett" in recalled.text.casefold()
                simulation = post(
                    path + "/simulations",
                    {
                        "character_ids": [lumia["id"], power["id"]],
                        "location_id": location["id"],
                        "max_rounds": 1,
                        "recognize_events": False,
                    },
                )
                post(
                    path + f"/simulations/{simulation['id']}/control/start",
                    {"revision": simulation["revision"]},
                )
                with SessionLocal() as db:
                    asyncio.run(step(db, simulation["id"], provider))
                result = client.get("/api" + path + f"/simulations/{simulation['id']}").json()
                report["simulation"] = result
                checks["simulation_without_extra_configuration"] = (
                    result["status"] == "completed"
                    and result["calls_used"] == 1
                    and not result["jobs"]
                    and bool(result["messages"])
                )
                checks["private_profile_isolated"] = all(
                    "POWER-PRIVAT-478" not in row["context"] for row in report["trace"]
                )
                memories = [row for row in report["trace"] if row["kind"] == "memory"]
                checks["memory_without_reasoning"] = bool(memories) and all(
                    row["diagnostics"].get("reasoning_tokens") == 0 for row in memories
                )
                checks["same_model_throughout"] = all(
                    row["model"] == args.model for row in report["trace"]
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
