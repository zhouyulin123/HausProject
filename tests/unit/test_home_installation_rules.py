"""显式安装、预留区、点位不依赖名称推断。"""

from copy import deepcopy
import pytest
from app.schemas.home_design import HomeDesignDocument
from app.schemas.spatial import SpatialDocument
from app.services.home_design_validation import validate_design
from tests.unit.test_home_design import document
from tests.unit.test_spatial_document import document as space_document


def check(value, space=None):
    space = space or space_document()
    space["scale_status"] = "confirmed"
    return validate_design(
        HomeDesignDocument.model_validate(value), SpatialDocument.model_validate(space)
    )


def test_old_serialization_unchanged():
    value = document()
    assert HomeDesignDocument.model_validate(value).model_dump(mode="json") == value


@pytest.mark.parametrize(
    "kind,y,code",
    [
        ("floor", 0.2, "installation_floor_gap"),
        ("ceiling", 0, "installation_ceiling_gap"),
    ],
)
def test_explicit_installation_contact(kind, y, code):
    value = document()
    value["objects"][0]["installation"] = {"kind": kind}
    value["objects"][0]["position"]["y"] = y
    assert code in {i.code for i in check(value).issues}


def test_clearance_rotation_and_unconfirmed():
    value = document()
    item = value["objects"][0]
    item["clearance"] = dict(front=2, back=0, left=0, right=0, above=0, confirmed=False)
    assert {"clearance_unconfirmed", "clearance_outside_room"} <= {
        i.code for i in check(value).issues
    }
    item["rotation"] = 90
    item["clearance"]["front"] = 1
    item["clearance"]["confirmed"] = True
    assert check(value).valid


def test_point_confirmation_distance_and_reference():
    value = document()
    value["points"] = [
        dict(
            id="p",
            name="插座",
            room_id="r1",
            kind="socket",
            position=dict(x=0, y=1, z=1),
            confirmed=False,
        )
    ]
    value["objects"][0]["point_requirement"] = dict(point_id="p", max_distance_m=0.2)
    assert {"point_unconfirmed", "point_distance_exceeded"} <= {
        i.code for i in check(value).issues
    }
    value["points"] = []
    with pytest.raises(ValueError):
        check(value)


def test_clearance_collision_with_other_item():
    value = document()
    item = value["objects"][0]
    item["clearance"] = dict(
        front=0.5, back=0, left=0, right=0, above=0, confirmed=True
    )
    other = deepcopy(item)
    other.pop("clearance")
    other["id"] = "other"
    other["position"]["z"] = 2.6
    value["objects"].append(other)
    assert "clearance_object_collision" in {i.code for i in check(value).issues}


def wall_space():
    space = space_document()
    space["walls"] = [
        dict(
            id="wall",
            start=dict(x=0, z=0),
            end=dict(x=4, z=0),
            room_ids=["r1"],
            height=2.8,
            thickness=0.2,
        )
    ]
    return space


@pytest.mark.parametrize(
    "rotation,z,valid",
    [(0, 0.6, True), (180, 0.6, False), (45, 0.6, False), (0, 0.7, False)],
)
def test_wall_back_face_contact(rotation, z, valid):
    value = document()
    item = value["objects"][0]
    item["installation"] = dict(kind="wall", wall_id="wall")
    item["position"]["z"] = z
    item["position"]["y"] = 1
    item["rotation"] = rotation
    assert (
        "installation_wall_contact"
        not in {i.code for i in check(value, wall_space()).issues}
    ) == valid


def test_host_opening_is_not_solid_mounting_face():
    value = document()
    value["objects"][0]["installation"] = dict(kind="wall", wall_id="wall")
    value["objects"][0]["position"]["z"] = 0.6
    space = wall_space()
    space["openings"] = [
        dict(id="door", wall_id="wall", type="door", offset=1, width=2, height=2.2)
    ]
    assert "installation_wall_contact" in {i.code for i in check(value, space).issues}


def test_host_reference_and_point_room_rejected():
    value = document()
    value["objects"][0]["installation"] = dict(kind="wall", wall_id="missing")
    with pytest.raises(ValueError, match="宿主"):
        check(value)
    value["objects"][0].pop("installation")
    value["points"] = [
        dict(
            id="p",
            name="网络",
            room_id="missing",
            kind="network",
            position=dict(x=1, y=1, z=1),
            confirmed=True,
        )
    ]
    with pytest.raises(ValueError, match="点位"):
        check(value)


def test_point_bounds_and_ceiling_attachment():
    value = document()
    value["points"] = [
        dict(
            id="p",
            name="网络",
            room_id="r1",
            kind="network",
            position=dict(x=10, y=3, z=1),
            confirmed=True,
        )
    ]
    value["objects"][0]["installation"] = dict(kind="ceiling")
    value["objects"][0]["position"]["y"] = 1.8
    codes = {i.code for i in check(value).issues}
    assert codes == {"point_outside_room", "point_above_ceiling"}


def test_clearance_wall_and_above():
    value = document()
    value["objects"][0]["clearance"] = dict(
        front=0, back=1.1, left=0, right=0, above=2, confirmed=True
    )
    assert {"clearance_wall_collision", "clearance_above_ceiling"} <= {
        i.code for i in check(value, wall_space()).issues
    }


def test_new_optional_values_serialize_and_duplicate_points_fail():
    value = document()
    item = value["objects"][0]
    item.update(installation=None, clearance=None, point_requirement=None)
    assert (
        HomeDesignDocument.model_validate(value).model_dump(mode="json") == document()
    )
    point = dict(
        id="p",
        name="网络",
        room_id="r1",
        kind="network",
        position=dict(x=1, y=1, z=1),
        confirmed=True,
    )
    value["points"] = [point, point]
    with pytest.raises(ValueError):
        HomeDesignDocument.model_validate(value)


def test_agent_cannot_assert_confirmed_and_preserves_existing_constraints():
    from app.schemas.home_design_agent import HomeDesignAgentPlan
    from app.services.home_design_agent_service import apply_plan

    value = document()
    value["objects"][0]["clearance"] = dict(
        front=0, back=0, left=0, right=0, above=0, confirmed=True
    )
    original = HomeDesignDocument.model_validate(value)
    added = deepcopy(value["objects"][0])
    added["id"] = "new"
    plan = HomeDesignAgentPlan.model_validate(
        dict(
            outcome="proposal",
            message="添加",
            operations=[dict(type="add_object", object=added)],
        )
    )
    with pytest.raises(ValueError, match="不能确认"):
        apply_plan(original, plan)
    patch = HomeDesignAgentPlan.model_validate(
        dict(
            outcome="proposal",
            message="改名",
            operations=[
                dict(type="patch_object", id="o1", changes=dict(name="新名字"))
            ],
        )
    )
    assert (
        apply_plan(original, patch).objects[0].clearance
        == original.objects[0].clearance
    )
    with pytest.raises(ValueError):
        HomeDesignAgentPlan.model_validate(
            dict(
                outcome="proposal",
                message="修改",
                operations=[
                    dict(
                        type="patch_object",
                        id="o1",
                        changes=dict(clearance=added["clearance"]),
                    )
                ],
            )
        )


def test_space_impact_reports_point_and_mount_host():
    from app.services.home_design_impact_service import reference_issues

    value = document()
    value["points"] = [
        dict(
            id="p",
            name="插座",
            room_id="missing",
            kind="socket",
            position=dict(x=1, y=1, z=1),
            confirmed=True,
        )
    ]
    value["objects"][0]["installation"] = dict(kind="wall", wall_id="gone")
    issues = reference_issues(
        HomeDesignDocument.model_validate(value),
        SpatialDocument.model_validate(space_document()),
    )
    assert {(i.entity_type, i.code) for i in issues} == {
        ("point", "room_missing"),
        ("object", "wall_missing"),
    }


@pytest.mark.parametrize("point_room,code", [(None, "point_missing"), ("other", "point_room_mismatch")])
def test_space_impact_reports_invalid_point_binding(point_room, code):
    from app.services.home_design_impact_service import reference_issues

    value = document()
    value["objects"][0]["point_requirement"] = {"point_id": "socket", "max_distance_m": 2}
    if point_room:
        value["points"] = [dict(id="socket", name="插座", room_id=point_room,
                                kind="socket", position=dict(x=1, y=0, z=1), confirmed=False)]
    issues = reference_issues(HomeDesignDocument.model_validate(value), SpatialDocument.model_validate(space_document()))
    assert any(i.entity_type == "object" and i.entity_id == "o1" and i.code == code for i in issues)
