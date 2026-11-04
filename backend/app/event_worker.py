import asyncio
import logging

from sqlalchemy import select

from .db import SessionLocal
from .extraction import run_job
from .models import EventSettings, ExtractionJob

log = logging.getLogger("openworld.extraction")


async def worker(app):
    app.state.event_worker_error = ""
    try:
        await run_worker(app)
    except Exception:
        log.exception("Local extraction worker stopped unexpectedly")
        app.state.event_worker_error = (
            "Ereignisverarbeitung nicht verfügbar. Bitte Backend-Protokoll prüfen und neu starten."
        )


async def run_worker(app):
    with SessionLocal() as db:
        for job in db.scalars(select(ExtractionJob).where(ExtractionJob.status == "running")):
            job.status = "failed"
            job.error = (
                "Server während der Extraktion beendet. Bei Bedarf bewusst erneut versuchen."
            )
        db.commit()
    while True:
        await asyncio.sleep(1)
        with SessionLocal() as db:
            job_id = db.scalar(
                select(ExtractionJob.id)
                .join(EventSettings, EventSettings.world_id == ExtractionJob.world_id)
                .where(
                    ExtractionJob.status == "pending",
                    EventSettings.enabled.is_(True),
                )
                .order_by(ExtractionJob.created_at, ExtractionJob.id)
                .limit(1)
            )
            if not job_id:
                continue
            try:
                await run_job(db, job_id, app.state.provider)
            except Exception:
                # Unexpected infrastructure failures must remain visible and never spin/retry.
                db.rollback()
                log.exception("Unexpected extraction failure in job %s", job_id)
                job = db.get(ExtractionJob, job_id)
                if job and job.status != "invalidated":
                    job.status = "failed"
                    job.error = "Interner Extraktionsfehler. Bitte Backend-Protokoll prüfen."
                    db.commit()
