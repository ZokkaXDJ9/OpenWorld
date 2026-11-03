import pytest
from conftest import create


def locations(client, path):
    return client.get("/api" + path + "/locations").json()


def snapshot(rows):
    return [
        {key: row[key] for key in ("id", "parent_id", "sort_order", "revision")}
        for row in rows
    ]


def save_tree(client, path, items):
    return client.put("/api" + path + "/location-tree", json={"locations": items})


def test_reparent_reorder_preserves_subtrees_content_and_character_locations(eldoria):
    e = eldoria
    client, path = e["client"], e["path"]
    room = create(
        client, path + "/locations", name="Raum", parent_id=e["glade"]["id"],
        description="Bleibt erhalten", tags=["privat"], state={"Wetter": "Regen"},
        attributes=[{"name": "Licht", "type": "boolean", "value": True}],
    )
    character = create(
        client, path + "/characters", name="Bewohner", location_id=room["id"],
        travel_status="present",
    )
    before = locations(client, path)
    items = snapshot(before)
    for item in items:
        if item["id"] == e["glade"]["id"]:
            item.update(parent_id=e["shadowfang"]["id"], sort_order=0)
    response = save_tree(client, path, items)
    assert response.status_code == 200, response.text
    after = {row["id"]: row for row in locations(client, path)}
    assert after[e["glade"]["id"]]["parent_id"] == e["shadowfang"]["id"]
    for key in ("parent_id", "description", "tags", "attributes", "state"):
        assert after[room["id"]][key] == room[key]
    assert all(after[row["id"]]["revision"] == row["revision"] + 1 for row in before)
    characters = client.get("/api" + path + "/characters").json()
    assert next(row for row in characters if row["id"] == character["id"]) == character


def test_order_survives_regular_edit_and_new_locations_append(eldoria):
    e = eldoria
    client, path = e["client"], e["path"]
    items = snapshot(locations(client, path))
    for item in items:
        item["sort_order"] = 1 - item["sort_order"]
    assert save_tree(client, path, items).status_code == 200
    first = locations(client, path)[0]
    assert first["id"] == e["glade"]["id"]
    response = client.put(
        "/api" + path + "/locations/" + first["id"],
        json={"name": "Umbenannt", "revision": first["revision"]},
    )
    assert response.status_code == 200
    assert response.json()["sort_order"] == 0
    added = create(client, path + "/locations", name="Zuletzt")
    assert added["sort_order"] == 2
    assert [row["id"] for row in locations(client, path)] == [
        first["id"], e["shadowfang"]["id"], added["id"],
    ]
    child = create(client, path + "/locations", name="Kind", parent_id=first["id"])
    response = client.put(
        "/api" + path + "/locations/" + child["id"],
        json={"name": "Kind", "revision": child["revision"], "parent_id": None},
    )
    assert response.status_code == 200
    assert response.json()["sort_order"] == 3


def test_stale_revision_rolls_back_every_location_even_after_first_update(eldoria):
    e = eldoria
    client, path = e["client"], e["path"]
    before = locations(client, path)
    items = snapshot(before)
    for item in items:
        item["sort_order"] = 1 - item["sort_order"]
    items[-1]["revision"] += 1
    assert save_tree(client, path, items).status_code == 409
    assert locations(client, path) == before


@pytest.mark.parametrize("change", ["self", "cycle", "foreign", "missing", "duplicate", "order"])
def test_invalid_tree_is_rejected_without_changes(eldoria, change):
    e = eldoria
    client, path = e["client"], e["path"]
    before = locations(client, path)
    items = snapshot(before)
    if change == "self":
        items[0]["parent_id"] = items[0]["id"]
    elif change == "cycle":
        items[0].update(parent_id=items[1]["id"], sort_order=0)
        items[1].update(parent_id=items[0]["id"], sort_order=0)
    elif change == "foreign":
        world = create(client, "/worlds", name="Fremde Welt")
        parent = create(client, f"/worlds/{world['id']}/locations", name="Fremder Ort")
        items[1].update(parent_id=parent["id"], sort_order=0)
    elif change == "missing":
        items.pop()
    elif change == "duplicate":
        items.append(items[0])
    else:
        items[1]["sort_order"] = items[0]["sort_order"]
    assert save_tree(client, path, items).status_code == (409 if change == "missing" else 422)
    assert locations(client, path) == before


@pytest.mark.parametrize("change", ["create", "delete", "edit"])
def test_concurrent_location_changes_reject_old_tree_snapshot(eldoria, change):
    e = eldoria
    client, path = e["client"], e["path"]
    added = create(client, path + "/locations", name="Nicht verwendet")
    items = snapshot(locations(client, path))
    if change == "create":
        create(client, path + "/locations", name="Neu")
    elif change == "delete":
        assert client.delete(
            "/api" + path + "/locations/" + added["id"] + "?revision=1"
        ).status_code == 204
    else:
        assert client.put(
            "/api" + path + "/locations/" + added["id"],
            json={"name": "Neuer Name", "revision": 1},
        ).status_code == 200
    before = locations(client, path)
    assert save_tree(client, path, items).status_code == 409
    assert locations(client, path) == before
