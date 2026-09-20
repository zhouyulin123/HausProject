"""扩展条件保持版本持久化与失败原子性。"""

from copy import deepcopy

from tests.integration.test_home_design_api import context, spatial_context  # noqa: F401
from tests.unit.test_home_design import document


def test_installation_and_points_persist_and_invalid_reference_does_not_advance(
    context,  # noqa: F811
):  # noqa: F811
    client, url, headers, _, _, _ = context
    value = document()
    value["points"] = [
        dict(
            id="p",
            name="插座",
            room_id="r1",
            kind="socket",
            position=dict(x=2, y=0, z=1.5),
            confirmed=True,
        )
    ]
    value["objects"][0].update(
        installation=dict(kind="floor"),
        point_requirement=dict(point_id="p", max_distance_m=0),
        clearance=dict(front=0, back=0, left=0, right=0, above=0, confirmed=False),
    )
    request = dict(base_version=0, client_mutation_id="installation", document=value)
    result = client.put(url, headers=headers, json=request)
    assert result.status_code == 200, result.text
    assert "clearance_unconfirmed" in {
        i["code"] for i in result.json()["validation"]["issues"]
    }
    assert client.put(url, headers=headers, json=request).json() == result.json()
    assert client.get(url + "/versions/1", headers=headers).json() == result.json()
    invalid = deepcopy(value)
    invalid["objects"][0]["point_requirement"]["point_id"] = "missing"
    response = client.put(
        url,
        headers=headers,
        json=dict(base_version=1, client_mutation_id="invalid", document=invalid),
    )
    assert response.status_code == 422
    assert client.get(url, headers=headers).json()["version"] == 1
