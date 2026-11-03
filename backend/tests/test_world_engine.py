import pytest
from conftest import create


def test_hierarchy_cycles_and_cross_world_references(eldoria):
    e = eldoria
    client, path = e["client"], e["path"]
    room = create(client, path + "/locations", name="Raum", parent_id=e["glade"]["id"])
    response = client.put(
        "/api" + path + "/locations/" + e["glade"]["id"],
        json={
            "name": "Glade",
            "parent_id": room["id"],
            "revision": 1,
        },
    )
    assert response.status_code == 422
    other = create(client, "/worlds", name="Andere Welt")
    response = client.post(
        f"/api/worlds/{other['id']}/characters",
        json={
            "name": "Fremder",
            "location_id": e["glade"]["id"],
            "travel_status": "present",
        },
    )
    assert response.status_code == 404
    assert (
        client.delete("/api" + path + "/locations/" + e["glade"]["id"] + "?revision=1").status_code
        == 409
    )


def test_revision_conflict_and_description_state_separation(eldoria):
    e = eldoria
    body = {
        "name": "Eldoria",
        "description": "Unveraenderte Geschichte",
        "state": {"Krieg": True},
        "revision": 1,
    }
    response = e["client"].put("/api" + e["path"], json=body)
    assert response.status_code == 200
    assert response.json()["description"] == "Unveraenderte Geschichte"
    assert response.json()["state"]["Krieg"] is True
    assert response.json()["revision"] == 2
    assert e["client"].put("/api" + e["path"], json=body).status_code == 409
    assert e["client"].delete("/api" + e["path"] + "?revision=1").status_code == 409
    body.pop("revision")
    assert e["client"].put("/api" + e["path"], json=body).status_code == 422


@pytest.mark.parametrize(
    "attribute",
    [
        {"name": "Text", "type": "text", "value": "Wald"},
        {"name": "Zahl", "type": "number", "value": 44, "minimum": 0, "maximum": 100},
        {"name": "Boolean", "type": "boolean", "value": True},
        {"name": "Auswahl", "type": "select", "value": "A", "options": ["A", "B"]},
        {"name": "Mehrfach", "type": "multiselect", "value": ["A", "B"], "options": ["A", "B"]},
        {"name": "Datum", "type": "date", "value": "2026-11-03"},
    ],
)
def test_attribute_types(environment, attribute):
    client, _, _ = environment
    world = create(client, "/worlds", name="Attribute", attributes=[attribute])
    assert world["attributes"][0]["value"] == attribute["value"]


@pytest.mark.parametrize(
    "attribute",
    [
        {"name": "Zahl", "type": "number", "value": True},
        {"name": "Zahl", "type": "number", "value": 101, "maximum": 100},
        {"name": "Boolean", "type": "boolean", "value": "ja"},
        {"name": "Auswahl", "type": "select", "value": "C", "options": ["A"]},
        {"name": "Datum", "type": "date", "value": "morgen"},
        {"name": "Ref", "type": "reference", "value": "missing"},
    ],
)
def test_invalid_attribute_values(environment, attribute):
    client, _, _ = environment
    assert (
        client.post(
            "/api/worlds",
            json={
                "name": "Ungueltig",
                "attributes": [attribute],
            },
        ).status_code
        == 422
    )


def test_reference_deletion_protection(eldoria):
    e = eldoria
    create(
        e["client"],
        e["path"] + "/locations",
        name="Tempel",
        attributes=[
            {"name": "Schutzpatron", "type": "reference", "value": e["power"]["id"]},
        ],
    )
    response = e["client"].delete(
        "/api" + e["path"] + "/characters/" + e["power"]["id"] + "?revision=1"
    )
    assert response.status_code == 409


def test_relationships_are_directed(eldoria):
    e = eldoria
    for source, target, trust in [(e["lumia"], e["power"], 90), (e["power"], e["lumia"], 35)]:
        create(
            e["client"],
            e["path"] + "/relationships",
            source_id=source["id"],
            target_id=target["id"],
            attributes=[
                {"name": "Vertrauen", "type": "number", "value": trust},
            ],
        )
    rows = e["client"].get("/api" + e["path"] + "/relationships").json()
    assert [row["attributes"][0]["value"] for row in rows] == [90, 35]


def test_world_deletion_cascades_all_data(eldoria):
    e = eldoria
    create(e["client"], e["path"] + "/locations", name="Haus", parent_id=e["glade"]["id"])
    response = e["client"].delete("/api" + e["path"] + "?revision=1")
    assert response.status_code == 204, response.text
    assert e["client"].get("/api/worlds").json() == []
    assert (
        e["client"].get(f"/api/conversations/{e['conversation']['id']}/messages").status_code == 404
    )


def test_openapi_documents_resource_request_shapes(environment):
    client, _, _ = environment
    spec = client.get("/openapi.json").json()
    request_body = spec["paths"]["/api/worlds/{world_id}/{resource}"]["post"]["requestBody"]
    assert request_body["required"] is True
    variants = request_body["content"]["application/json"]["schema"]["anyOf"]
    assert {variant["title"] for variant in variants} == {
        "LocationInput",
        "CharacterInput",
        "RelationshipInput",
        "KnowledgeInput",
    }
    assert "Attribute" in spec["components"]["schemas"]
