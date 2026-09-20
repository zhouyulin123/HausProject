"""独立验证户型影响预览不改历史，且冻结家具不会被悄然挪动。"""

from copy import deepcopy

from tests.integration.test_home_assets_independent import (  # noqa: F401
    assets_context,
    spatial_context,
    freeze,
    bound_document,
)
from tests.integration.test_spatial_api import request


def test_impact_keeps_frozen_asset_and_history_until_explicit_save(assets_context):
    client, _, url, headers, _, source_id, _ = assets_context
    asset = freeze(client, url, headers, source_id).json()
    document = bound_document(asset)
    saved = client.put(url, headers=headers, json={
        "base_version": 0, "client_mutation_id": "initial-home", "document": document,
    })
    assert saved.status_code == 200, saved.text
    old_delivery = client.get(url + "/versions/1/delivery", headers=headers).json()
    space_url = url.replace("/home-design", "/space")
    target = request(1, "smaller-room")
    target["document"]["scale_status"] = "confirmed"
    target["document"]["rooms"][0]["polygon"] = [
        {"x": 0, "z": 0}, {"x": 1, "z": 0}, {"x": 1, "z": 3}, {"x": 0, "z": 3},
    ]
    target["document"]["walls"] = []
    target["document"]["openings"] = []
    created = client.put(space_url, headers=headers, json=target)
    assert created.status_code == 200, created.text
    result = client.post(url + "/space-impact", headers=headers, json={
        "document": document, "target_space_version": 2,
    })
    assert result.status_code == 200, result.text
    impact = result.json()
    assert impact["can_apply"]
    assert not impact["validation"]["valid"]
    assert "object_outside_room" in {i["code"] for i in impact["validation"]["issues"]}
    assert impact["candidate_document"]["objects"] == document["objects"]
    assert impact["candidate_document"]["space_version"] == 2
    assert client.get(url, headers=headers).json() == saved.json()
    assert client.get(url + "/versions/1/delivery", headers=headers).json() == old_delivery
    next_save = client.put(url, headers=headers, json={
        "base_version": 1, "client_mutation_id": "apply-impact",
        "document": impact["candidate_document"],
    })
    assert next_save.status_code == 200, next_save.text
    assert next_save.json()["version"] == 2
    assert client.get(url + "/versions/1/delivery", headers=headers).json() == old_delivery


def test_reassignment_is_explicit_and_foreign_asset_stays_forbidden(assets_context):
    client, _, url, headers, stranger, source_id, _ = assets_context
    asset = freeze(client, url, headers, source_id).json()
    document = bound_document(asset)
    target = request(1, "replace-room")
    target["document"]["scale_status"] = "confirmed"
    target["document"]["rooms"][0]["id"] = "replacement"
    target["document"]["walls"] = []
    target["document"]["openings"] = []
    result = client.put(url.replace("/home-design", "/space"), headers=headers, json=target)
    assert result.status_code == 200, result.text
    payload = {"document": document, "target_space_version": 2}
    preview = client.post(url + "/space-impact", headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    assert not preview.json()["can_apply"]
    assert preview.json()["reference_issues"]
    assert preview.json()["candidate_document"]["objects"] == document["objects"]
    resolved = deepcopy(payload)
    resolved["document"]["objects"][0]["room_id"] = "replacement"
    accepted = client.post(url + "/space-impact", headers=headers, json=resolved)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["can_apply"]
    assert accepted.json()["candidate_document"]["objects"][0]["asset_id"] == asset["id"]
    assert client.post(url + "/space-impact", headers={"X-Session-ID": stranger}, json=payload).status_code == 404
    resolved["document"]["objects"][0]["asset_id"] = 987654
    assert client.post(url + "/space-impact", headers=headers, json=resolved).status_code == 422
