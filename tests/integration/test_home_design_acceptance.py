"""独立验收：空间换绑、历史恢复与只读校验不污染已保存版本。"""

from copy import deepcopy

from app.db.models import DesignSpace, DesignSpaceVersion, DesignTask
from tests.integration.test_home_design_api import context, payload  # noqa: F401
from tests.integration.test_spatial_api import (  # noqa: F401
    context as spatial_context,
    request as space_request,
)


def test_space_rebind_revalidates_without_rewriting_history(context):  # noqa: F811
    client, url, headers, _, spatial, space_url = context
    confirmed = space_request(1, "confirmed")
    confirmed["document"]["scale_status"] = "confirmed"
    assert spatial.put(space_url, headers=headers, json=confirmed).status_code == 200
    first = payload()
    first["document"]["space_version"] = 2
    first["document"]["objects"][0]["size"]["height"] = 2.5
    saved = client.put(url, headers=headers, json=first)
    assert saved.status_code == 200
    assert saved.json()["validation"]["valid"]

    lower_ceiling = deepcopy(confirmed)
    lower_ceiling.update(base_version=2, client_mutation_id="lower-ceiling")
    lower_ceiling["document"]["rooms"][0]["height"] = 2.2
    assert spatial.put(space_url, headers=headers, json=lower_ceiling).status_code == 200
    assert client.get(url, headers=headers).json() == saved.json()

    rebound = payload(1, "rebind")
    rebound["document"]["objects"][0]["size"]["height"] = 2.5
    rebound["document"]["space_version"] = 3
    result = client.put(url, headers=headers, json=rebound)
    assert result.status_code == 200
    assert "object_above_ceiling" in {
        issue["code"] for issue in result.json()["validation"]["issues"]
    }
    assert client.get(url + "/versions/1", headers=headers).json() == saved.json()
    restore = deepcopy(first)
    restore.update(base_version=2, client_mutation_id="restore")
    restored = client.put(url, headers=headers, json=restore).json()
    assert restored["version"] == 3
    assert restored["document"] == saved.json()["document"]
    assert restored["validation"]["valid"]


def test_validation_is_read_only_and_ignores_no_geometry_errors(context):  # noqa: F811
    client, url, headers, _, _, _ = context
    first = client.put(url, headers=headers, json=payload()).json()
    invalid = deepcopy(first["document"])
    invalid["objects"][0]["position"]["x"] = 999
    result = client.post(url + "/validate", headers=headers, json=invalid)
    assert result.status_code == 200
    assert not result.json()["valid"]
    assert "object_outside_room" in {
        issue["code"] for issue in result.json()["issues"]
    }
    assert client.get(url, headers=headers).json() == first
    assert len(client.get(url + "/versions", headers=headers).json()["versions"]) == 1


def test_foreign_space_version_cannot_supply_missing_owned_version(context, spatial_context):  # noqa: F811
    client, url, headers, _, _, _ = context
    _, factory, _, _, _ = spatial_context
    with factory() as db:
        other = DesignTask(status="waiting_input")
        db.add(other)
        db.flush()
        db.add(DesignSpace(task_id=other.id, current_version=99))
        db.flush()
        db.add(DesignSpaceVersion(
            task_id=other.id,
            version=99,
            document_json=space_request()["document"],
            client_mutation_id="foreign-space",
            mutation_digest="0" * 64,
        ))
        db.commit()
    missing = payload()
    missing["document"]["space_version"] = 99
    assert client.put(url, headers=headers, json=missing).status_code == 422
    assert client.get(url, headers=headers).json()["version"] == 0
