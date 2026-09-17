"""历史读取、权限和精确房间投影。"""
from tests.integration.test_spatial_api import context as _context, request

context = _context


def test_history_pagination_and_ownership(context):
    client, _, url, headers, stranger = context
    for version in range(3):
        payload = request(version, f"version-{version}")
        payload["document"]["rooms"][0]["name"] = f"房间 {version}"
        assert client.put(url, headers=headers, json=payload).status_code == 200
    result = client.get(url + "/versions?limit=2", headers=headers)
    assert result.status_code == 200
    assert [v["version"] for v in result.json()["versions"]] == [3, 2]
    assert result.json()["next_before_version"] == 2
    tail = client.get(url + "/versions?limit=2&before_version=2", headers=headers).json()
    assert [v["version"] for v in tail["versions"]] == [1]
    assert tail["next_before_version"] is None
    old = client.get(url + "/versions/1", headers=headers).json()
    assert old["document"]["rooms"][0]["name"] == "房间 0"
    for suffix in ["/versions", "/versions/1", "/versions/1/source", "/versions/1/rooms/r1/scene"]:
        assert client.get(url + suffix, headers={"X-Session-Id": stranger}).status_code == 404
    assert client.get(url + "/versions/99", headers=headers).status_code == 404
    assert client.get(url + "/versions?limit=1000", headers=headers).status_code == 422


def test_projection_never_invents_scale_or_room(context):
    client, _, url, headers, _ = context
    assert client.put(url, headers=headers, json=request()).status_code == 200
    assert client.get(url + "/versions/1/rooms/r1/scene", headers=headers).status_code == 422
    assert client.get(url + "/versions/1/rooms/missing/scene", headers=headers).status_code == 404


def test_projection_preserves_coordinates_and_history(context):
    client, _, url, headers, _ = context
    payload = request()
    doc = payload["document"]
    doc["scale_status"] = "confirmed"
    polygon = doc["rooms"][0]["polygon"]
    doc["walls"] = [{"id": f"w{i}", "start": a, "end": polygon[(i+1)%4],
                     "room_ids": ["r1"], "height": 2.8, "thickness": 0.15} for i,a in enumerate(polygon)]
    doc["openings"] = [{"id":"door", "wall_id":"w0", "type":"door", "offset":1,
                        "width":0.8, "height":2.1, "sill_height":0}]
    assert client.put(url, headers=headers, json=payload).status_code == 200
    result = client.get(url + "/versions/1/rooms/r1/scene", headers=headers)
    assert result.status_code == 200, result.text
    projection = result.json()
    assert projection["space_version"] == 1
    assert projection["scene"]["room"]["floorPolygon"] == polygon
    assert projection["scene"]["room"]["wallThickness"] == 0.15
    assert projection["scene"]["openings"][0]["offset"] == 1
    assert client.get(url, headers=headers).json()["version"] == 1
