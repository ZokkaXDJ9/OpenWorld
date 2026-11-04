import copy
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_simulation import SceneProvider, control, run, setup

from app.db import Base, get_db, make_engine
from app.main import app
from app.models import Character, ProviderSettings, Simulation, World


@contextmanager
def target(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'import.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    previous = app.dependency_overrides[get_db]

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    try:
        yield factory
    finally:
        app.dependency_overrides[get_db] = previous
        engine.dispose()


def export(e):
    response = e["client"].get("/api" + e["path"] + "/export")
    assert response.status_code == 200, response.text
    return response.json()


def test_complete_world_roundtrip_keeps_stable_ids_and_excludes_provider_configuration(
    eldoria, tmp_path
):
    e = eldoria
    simulation = control(e, setup(e), "start").json()
    first = run(e, simulation, SceneProvider("Ich besitze einen blauen Kristall."))
    run(e, first, SceneProvider())
    with e["factory"]() as db:
        db.get(ProviderSettings, 1).encrypted_key = "private-provider-value"
        db.get(Simulation, simulation["id"]).model = r"C:\Private\model"
        db.commit()
    bundle = export(e)
    assert "private-provider-value" not in str(bundle)
    assert r"C:\Private" not in str(bundle)
    assert not {"provider_settings", "extraction_provider_settings"} & bundle["tables"].keys()
    with target(tmp_path) as factory:
        response = e["client"].post("/api/worlds/import", json=bundle)
        assert response.status_code == 201, response.text
        assert response.json()["id"] == e["world"]["id"]
        restored = export(e)
        assert restored == bundle
        with factory() as db:
            assert db.get(Character, e["power"]["id"]).profile == e["power"]["profile"]
            assert db.get(Simulation, simulation["id"]).completed_rounds == 2
            assert not list(db.scalars(select(ProviderSettings)))
        duplicate = e["client"].post("/api/worlds/import", json=bundle)
        assert duplicate.status_code == 409
        assert export(e) == restored


def test_broken_reference_and_unknown_tables_are_rejected_without_partial_import(eldoria, tmp_path):
    e = eldoria
    bundle = export(e)
    broken = copy.deepcopy(bundle)
    broken["tables"]["characters"][0]["location_id"] = "missing-location"
    with target(tmp_path) as factory:
        for data in [
            broken,
            {**bundle, "version": 999},
            {**bundle, "tables": {**bundle["tables"], "provider_settings": []}},
        ]:
            response = e["client"].post("/api/worlds/import", json=data)
            assert response.status_code == 422, response.text
            with factory() as db:
                assert not list(db.scalars(select(World)))
                assert not list(db.scalars(select(Character)))


def test_invalid_domain_value_rolls_back_whole_import(eldoria, tmp_path):
    e = eldoria
    bundle = export(e)
    bundle["tables"]["characters"][0]["attributes"] = [
        {
            "name": "Fremde Referenz",
            "type": "reference",
            "value": "outside-world",
            "options": [],
        }
    ]
    with target(tmp_path) as factory:
        response = e["client"].post("/api/worlds/import", json=bundle)
        assert response.status_code == 422, response.text
        with factory() as db:
            assert not list(db.scalars(select(World)))


def test_running_simulation_requires_pause_before_export(eldoria):
    e = eldoria
    control(e, setup(e), "start")
    response = e["client"].get("/api" + e["path"] + "/export")
    assert response.status_code == 409


def test_imported_pending_jobs_never_run_automatically(eldoria, tmp_path):
    e = eldoria
    simulation = setup(e)
    response = e["client"].post(
        "/api" + e["path"] + f"/simulations/{simulation['id']}/interventions",
        json={"revision": simulation["revision"], "content": "Eine konkrete Aussage."},
    )
    assert response.status_code == 201
    bundle = export(e)
    assert any(row["status"] == "pending" for row in bundle["tables"]["extraction_jobs"])
    with target(tmp_path):
        response = e["client"].post("/api/worlds/import", json=bundle)
        assert response.status_code == 201, response.text
        restored = export(e)
        assert all(row["status"] == "failed" for row in restored["tables"]["extraction_jobs"])
        assert restored["tables"]["simulations"][0]["status"] == "created"
        assert restored["tables"]["simulations"][0]["calls_used"] == 0


def test_import_rejects_identity_changes_inside_undo_snapshots(eldoria, tmp_path):
    e = eldoria
    simulation = control(e, setup(e), "start", steps=1).json()
    run(e, simulation, SceneProvider())
    bundle = export(e)
    bundle["tables"]["event_mutations"][0]["before"]["world_id"] = "foreign-world"
    with target(tmp_path) as factory:
        response = e["client"].post("/api/worlds/import", json=bundle)
        assert response.status_code == 422, response.text
        with factory() as db:
            assert not list(db.scalars(select(World)))
