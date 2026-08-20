"""3D 场景几何与空间语义工具：多边形、碰撞、动线检测。

scene_service 的空间校验与 M2 布局引擎共用，保证同一套几何口径。
所有函数为纯函数，只依赖 SceneItem 的属性（dimensions/transform/scale）。
"""

from math import cos, hypot, sin

# 门口内侧净空深度（米）
DOOR_CLEARANCE_DEPTH = 0.9
# 不参与物理碰撞阻挡的类别（不产生虚假家具碰撞）
NON_BLOCKING_CATEGORIES = {"地毯", "窗帘"}


def point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    epsilon: float = 1e-8,
) -> bool:
    px, pz = point
    x1, z1 = start
    x2, z2 = end
    cross = (px - x1) * (z2 - z1) - (pz - z1) * (x2 - x1)
    if abs(cross) > epsilon:
        return False
    return (
        min(x1, x2) - epsilon <= px <= max(x1, x2) + epsilon
        and min(z1, z2) - epsilon <= pz <= max(z1, z2) + epsilon
    )


def point_in_polygon(
    point: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> bool:
    inside = False
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        if point_on_segment(point, start, end):
            return True
        x1, z1 = start
        x2, z2 = end
        if (z1 > point[1]) != (z2 > point[1]):
            crossing_x = (x2 - x1) * (point[1] - z1) / (z2 - z1) + x1
            if point[0] < crossing_x:
                inside = not inside
    return inside


def item_footprint(item) -> list[tuple[float, float]] | None:
    """家具旋转后的完整占地多边形（米制）；无尺寸时返回 None。"""
    if item.dimensions is None:
        return None
    half_x = item.dimensions.x * item.transform.scale.x / 2
    half_z = item.dimensions.z * item.transform.scale.z / 2
    angle = item.transform.rotation.y
    cosine = cos(angle)
    sine = sin(angle)
    center_x = item.transform.position.x
    center_z = item.transform.position.z
    return [
        (
            center_x + local_x * cosine + local_z * sine,
            center_z - local_x * sine + local_z * cosine,
        )
        for local_x, local_z in (
            (-half_x, -half_z),
            (half_x, -half_z),
            (half_x, half_z),
            (-half_x, half_z),
        )
    ]


def project_polygon(
    polygon: list[tuple[float, float]],
    axis: tuple[float, float],
) -> tuple[float, float]:
    values = [point[0] * axis[0] + point[1] * axis[1] for point in polygon]
    return min(values), max(values)


def polygons_overlap(
    first: list[tuple[float, float]],
    second: list[tuple[float, float]],
    epsilon: float = 1e-6,
) -> bool:
    """SAT 分离轴检测两个凸多边形（家具占地）是否重叠。"""
    for polygon in (first, second):
        for start, end in zip(polygon, polygon[1:] + polygon[:1]):
            axis = (-(end[1] - start[1]), end[0] - start[0])
            first_range = project_polygon(first, axis)
            second_range = project_polygon(second, axis)
            if (
                first_range[1] <= second_range[0] + epsilon
                or second_range[1] <= first_range[0] + epsilon
            ):
                return False
    return True


def vertical_ranges_overlap(first, second, epsilon: float = 1e-6) -> bool:
    """两个家具的垂直高度区间是否重叠（用于判断是否可能物理碰撞）。"""
    if first.dimensions is None or second.dimensions is None:
        return False
    first_half = first.dimensions.y * first.transform.scale.y / 2
    second_half = second.dimensions.y * second.transform.scale.y / 2
    return (
        first.transform.position.y + first_half
        > second.transform.position.y - second_half + epsilon
        and second.transform.position.y + second_half
        > first.transform.position.y - first_half + epsilon
    )


def door_clearance_polygon(
    polygon: list[tuple[float, float]],
    *,
    wall_index: int,
    offset: float,
    width: float,
) -> list[tuple[float, float]]:
    """门/洞口内侧的净空矩形（米制），家具不得占用。"""
    start = polygon[wall_index]
    end = polygon[(wall_index + 1) % len(polygon)]
    wall_length = hypot(end[0] - start[0], end[1] - start[1])
    tangent = (
        (end[0] - start[0]) / wall_length,
        (end[1] - start[1]) / wall_length,
    )
    door_center = (
        start[0] + tangent[0] * (offset + width / 2),
        start[1] + tangent[1] * (offset + width / 2),
    )
    left_normal = (-tangent[1], tangent[0])
    probe_distance = 1e-4
    left_probe = (
        door_center[0] + left_normal[0] * probe_distance,
        door_center[1] + left_normal[1] * probe_distance,
    )
    inward = (
        left_normal
        if point_in_polygon(left_probe, polygon)
        else (-left_normal[0], -left_normal[1])
    )
    half_width = width / 2
    depth = DOOR_CLEARANCE_DEPTH
    inner_center = (
        door_center[0] + inward[0] * depth / 2,
        door_center[1] + inward[1] * depth / 2,
    )
    return [
        (
            inner_center[0] + tangent[0] * side * half_width
            + inward[0] * direction * depth / 2,
            inner_center[1] + tangent[1] * side * half_width
            + inward[1] * direction * depth / 2,
        )
        for side, direction in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]
