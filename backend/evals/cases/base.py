"""评测案例通用结构：跨空间（客厅/卧室/餐厅/书房）共享。"""

from dataclasses import dataclass, field

from app.services.layout_generator import LayoutFurniture


@dataclass
class RoomCase:
    """一个空间评测案例：几何 + 家具清单 + 门窗洞口。"""

    id: str
    name: str
    room_width_m: float
    room_depth_m: float
    # living / bedroom / dining / study：用于评测分组统计
    group: str = "living"
    ceiling_height_m: float = 2.8
    furniture: list[LayoutFurniture] = field(default_factory=list)
    # 简化洞口描述，runner 转成 Opening（offset/width 为米制）
    openings: list[dict] = field(default_factory=list)


def make_furniture(
    sku: str,
    name: str,
    category: str,
    width_m: float,
    depth_m: float,
    height_m: float,
) -> LayoutFurniture:
    return LayoutFurniture(
        sku=sku,
        name=name,
        category=category,
        width_m=width_m,
        depth_m=depth_m,
        height_m=height_m,
    )
