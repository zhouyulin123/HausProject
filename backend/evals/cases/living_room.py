"""20 个标准客厅评测案例：覆盖尺寸、家具组合与门窗情况。

每个案例描述一个矩形客厅的几何、家具清单（真实尺寸）与门窗洞口。
评测 runner 会为每个案例跑完整的确定性布局生成（含 repair），
统计"无需手动救场即可打开渲染"的比例（以布局有效作为代理指标）。

坐标约定：房间中心在原点，z 负方向为后墙（沙发通常贴后墙），
wall_index 0=底边(后墙) / 1=右边 / 2=顶边(前墙) / 3=左边。
Opening 的 offset/width 为米制，offset 沿墙从该边起点算起。
"""

from evals.cases.base import RoomCase as LivingRoomCase
from evals.cases.base import make_furniture as _f


# ---- 家具库 ----
SOFA = _f("SOFA-001", "云朵三人沙发", "沙发", 2.2, 0.95, 0.85)
SOFA_L = _f("SOFA-002", "L型转角沙发", "沙发", 3.2, 1.6, 0.85)
TV = _f("TV-001", "电视收纳柜", "柜子", 1.6, 0.4, 1.9)
TV_WIDE = _f("TV-002", "整墙电视柜", "柜子", 3.0, 0.4, 2.2)
TEA = _f("TEA-001", "岩板茶几", "茶几", 1.0, 0.55, 0.42)
RUG = _f("RUG-001", "客厅地毯", "地毯", 2.0, 2.9, 0.02)
LAMP = _f("LAMP-001", "落地灯", "灯具", 0.4, 0.4, 1.5)
CHAIR = _f("CHAIR-001", "休闲椅", "休闲椅", 0.8, 0.8, 0.9)
SIDE = _f("SIDE-001", "边柜", "柜子", 0.9, 0.4, 0.9)
PLANT = _f("PLANT-001", "落地绿植", "其他", 0.5, 0.5, 1.6)

# ---- 门窗（米制；offset 沿墙起点算起）----
DOOR_BACK = {"type": "door", "wall_index": 0, "offset": 0.6, "width": 0.9, "height": 2.1, "sill_height": 0}
DOOR_FRONT = {"type": "door", "wall_index": 2, "offset": 0.6, "width": 0.9, "height": 2.1, "sill_height": 0}
DOOR_SIDE = {"type": "door", "wall_index": 3, "offset": 1.0, "width": 0.9, "height": 2.1, "sill_height": 0}
WINDOW_SIDE = {"type": "window", "wall_index": 1, "offset": 1.2, "width": 1.8, "height": 1.5, "sill_height": 0.9}
WINDOW_BACK = {"type": "window", "wall_index": 0, "offset": 2.0, "width": 1.8, "height": 1.5, "sill_height": 0.9}


CASES: list[LivingRoomCase] = [
    # ---- 基础三件套 × 三种尺寸 ----
    LivingRoomCase("living-01", "小客厅 3.6×4.2 · 三件套", 3.6, 4.2,
                   furniture=[SOFA, TV, TEA]),
    LivingRoomCase("living-02", "标准客厅 4.6×5.6 · 三件套", 4.6, 5.6,
                   furniture=[SOFA, TV, TEA]),
    LivingRoomCase("living-03", "大客厅 5.8×7.0 · 三件套", 5.8, 7.0,
                   furniture=[SOFA, TV, TEA]),

    # ---- 三件套 + 软装组合 ----
    LivingRoomCase("living-04", "小客厅 · 三件套+地毯+灯具", 3.6, 4.2,
                   furniture=[SOFA, TV, TEA, RUG, LAMP]),
    LivingRoomCase("living-05", "标准客厅 · 三件套+地毯+灯具", 4.6, 5.6,
                   furniture=[SOFA, TV, TEA, RUG, LAMP]),
    LivingRoomCase("living-06", "大客厅 · 三件套+地毯+灯具+休闲椅", 5.8, 7.0,
                   furniture=[SOFA, TV, TEA, RUG, LAMP, CHAIR]),

    # ---- 边柜 / 休闲椅变体 ----
    LivingRoomCase("living-07", "标准客厅 · 三件套+边柜", 4.6, 5.6,
                   furniture=[SOFA, TV, TEA, SIDE]),
    LivingRoomCase("living-08", "标准客厅 · 三件套+休闲椅+地毯", 4.6, 5.6,
                   furniture=[SOFA, TV, TEA, CHAIR, RUG]),
    LivingRoomCase("living-09", "标准客厅 · L型沙发+电视柜+茶几", 4.6, 5.6,
                   furniture=[SOFA_L, TV, TEA]),
    LivingRoomCase("living-10", "大客厅 · L型沙发+整墙电视柜+茶几", 5.8, 7.0,
                   furniture=[SOFA_L, TV_WIDE, TEA]),

    # ---- 门窗情况 ----
    LivingRoomCase("living-11", "标准客厅 · 门在沙发墙", 4.6, 5.6,
                   furniture=[SOFA, TV, TEA], openings=[DOOR_BACK]),
    LivingRoomCase("living-12", "标准客厅 · 门在电视柜墙", 4.6, 5.6,
                   furniture=[SOFA, TV, TEA], openings=[DOOR_FRONT]),
    LivingRoomCase("living-13", "标准客厅 · 侧门+侧窗", 4.6, 5.6,
                   furniture=[SOFA, TV, TEA], openings=[DOOR_SIDE, WINDOW_SIDE]),
    LivingRoomCase("living-14", "小客厅 · 后窗", 3.6, 4.2,
                   furniture=[SOFA, TV, TEA], openings=[WINDOW_BACK]),
    LivingRoomCase("living-15", "大客厅 · 门+窗", 5.8, 7.0,
                   furniture=[SOFA, TV, TEA], openings=[DOOR_BACK, WINDOW_SIDE]),

    # ---- 简化与满配 ----
    LivingRoomCase("living-16", "标准客厅 · 沙发+电视柜（无茶几）", 4.6, 5.6,
                   furniture=[SOFA, TV]),
    LivingRoomCase("living-17", "标准客厅 · 三件套+灯具（无地毯）", 4.6, 5.6,
                   furniture=[SOFA, TV, TEA, LAMP]),
    LivingRoomCase("living-18", "标准客厅 · 三件套+休闲椅（无地毯灯具）", 4.6, 5.6,
                   furniture=[SOFA, TV, TEA, CHAIR]),
    LivingRoomCase("living-19", "大客厅 · 满配（边柜+灯具+休闲椅）", 5.8, 7.0,
                   furniture=[SOFA, TV, TEA, SIDE, LAMP, CHAIR, RUG]),
    LivingRoomCase("living-20", "标准客厅 · 三件套+绿植+灯具", 4.6, 5.6,
                   furniture=[SOFA, TV, TEA, PLANT, LAMP]),
]
