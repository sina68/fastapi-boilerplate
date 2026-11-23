from __future__ import annotations

import uuid

from helpers import EMAIL, PASSWORD, register_and_login

ITEMS_URL = "/api/v1/items"


async def test_items_require_authentication(client):
    assert (await client.get(ITEMS_URL)).status_code == 401
    assert (await client.post(ITEMS_URL, json={"title": "x"})).status_code == 401


async def test_create_and_read_item(client, headers):
    created = await client.post(
        ITEMS_URL, json={"title": "Buy milk", "description": "2 litres"}, headers=headers
    )
    assert created.status_code == 201
    item = created.json()
    assert item["title"] == "Buy milk"

    fetched = await client.get(f"{ITEMS_URL}/{item['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["description"] == "2 litres"


async def test_list_is_scoped_to_owner(client, headers):
    await client.post(ITEMS_URL, json={"title": "mine"}, headers=headers)

    other_headers = await register_and_login(client, email="other@example.com")
    listed = await client.get(ITEMS_URL, headers=other_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 0
    assert listed.json()["items"] == []


async def test_other_users_item_is_not_found(client, headers):
    created = await client.post(ITEMS_URL, json={"title": "private"}, headers=headers)
    item_id = created.json()["id"]

    other_headers = await register_and_login(client, email="other@example.com")
    response = await client.get(f"{ITEMS_URL}/{item_id}", headers=other_headers)
    # 404, not 403: exists or not must look identical to a stranger.
    assert response.status_code == 404
    assert response.json()["code"] == "item_not_found"


async def test_foreign_item_cannot_be_deleted(client, headers):
    created = await client.post(ITEMS_URL, json={"title": "keep me"}, headers=headers)
    item_id = created.json()["id"]

    other_headers = await register_and_login(client, email="other@example.com")
    assert (await client.delete(f"{ITEMS_URL}/{item_id}", headers=other_headers)).status_code == 404
    assert (await client.get(f"{ITEMS_URL}/{item_id}", headers=headers)).status_code == 200


async def test_update_item(client, headers):
    created = await client.post(ITEMS_URL, json={"title": "old"}, headers=headers)
    item_id = created.json()["id"]

    patched = await client.patch(
        f"{ITEMS_URL}/{item_id}", json={"title": "new", "description": None}, headers=headers
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "new"
    assert patched.json()["description"] is None


async def test_delete_item(client, headers):
    created = await client.post(ITEMS_URL, json={"title": "gone"}, headers=headers)
    item_id = created.json()["id"]

    assert (await client.delete(f"{ITEMS_URL}/{item_id}", headers=headers)).status_code == 204
    assert (await client.get(f"{ITEMS_URL}/{item_id}", headers=headers)).status_code == 404


async def test_create_validates_payload(client, headers):
    empty_title = await client.post(ITEMS_URL, json={"title": ""}, headers=headers)
    assert empty_title.status_code == 422
    assert empty_title.json()["code"] == "validation_error"


async def test_patch_null_title_is_rejected_before_sql(client, headers):
    created = await client.post(ITEMS_URL, json={"title": "keep me"}, headers=headers)
    item_id = created.json()["id"]

    response = await client.patch(f"{ITEMS_URL}/{item_id}", json={"title": None}, headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    # The row is untouched, not half-written.
    assert (await client.get(f"{ITEMS_URL}/{item_id}", headers=headers)).json()[
        "title"
    ] == "keep me"


async def test_list_pagination(client, headers):
    for index in range(3):
        await client.post(ITEMS_URL, json={"title": f"item {index}"}, headers=headers)

    page = await client.get(f"{ITEMS_URL}?limit=2&offset=1", headers=headers)
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2 and body["offset"] == 1


async def test_unknown_and_malformed_ids_return_404(client, headers):
    assert (await client.get(f"{ITEMS_URL}/{uuid.uuid4()}", headers=headers)).status_code == 404
    assert (await client.get(f"{ITEMS_URL}/not-a-uuid", headers=headers)).status_code == 404


async def test_pagination_limits_are_enforced(client, headers):
    assert (await client.get(f"{ITEMS_URL}?limit=500", headers=headers)).status_code == 422
    assert (await client.get(f"{ITEMS_URL}?offset=-1", headers=headers)).status_code == 422


async def test_password_literal_never_echoed_in_validation_errors(client):
    secret = "hunter2"
    response = await client.post("/api/v1/auth/register", json={"email": EMAIL, "password": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert PASSWORD not in response.text
