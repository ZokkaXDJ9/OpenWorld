import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event

from app.simulation import clock_for


def test_concurrent_first_clock_reads_create_exactly_one_clock(eldoria):
    e = eldoria
    engine = e["factory"].kw["bind"]
    barrier = threading.Barrier(2)
    local = threading.local()

    def synchronize(connection, cursor, statement, parameters, context, executemany):
        if "FROM world_clocks" in statement and not getattr(local, "checked", False):
            local.checked = True
            barrier.wait(timeout=10)

    def read():
        with e["factory"]() as db:
            clock = clock_for(db, e["world"]["id"])
            db.commit()
            return clock.id, clock.elapsed_minutes

    event.listen(engine, "after_cursor_execute", synchronize)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: read(), range(2)))
        assert results == [(e["world"]["id"], 0)] * 2
    finally:
        event.remove(engine, "after_cursor_execute", synchronize)
