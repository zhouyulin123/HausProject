"""餐厅评测案例：覆盖餐桌尺寸、餐椅数量与餐边柜组合。"""

from evals.cases.base import RoomCase
from evals.cases.base import make_furniture as _f

TABLE = _f("TABLE-001", "四人圆餐桌", "餐桌", 1.2, 1.2, 0.75)
TABLE_BIG = _f("TABLE-002", "六人长餐桌", "餐桌", 1.6, 0.9, 0.75)
CHAIR = _f("CHAIR-001", "餐椅", "餐椅", 0.5, 0.5, 0.9)
SIDEBOARD = _f("SIDEBOARD-001", "餐边柜", "柜子", 1.2, 0.4, 0.9)

CASES: list[RoomCase] = [
    RoomCase("dining-01", "小餐厅 2.8×3.6 · 餐桌+餐椅×2+餐边柜", 2.8, 3.6, group="dining",
             furniture=[TABLE, CHAIR, CHAIR, SIDEBOARD]),
    RoomCase("dining-02", "标准餐厅 3.6×3.8 · 餐桌+餐椅×4", 3.6, 3.8, group="dining",
             furniture=[TABLE, CHAIR, CHAIR, CHAIR, CHAIR]),
    RoomCase("dining-03", "标准餐厅 3.6×3.8 · 餐桌+餐椅×4+餐边柜", 3.6, 3.8, group="dining",
             furniture=[TABLE, CHAIR, CHAIR, CHAIR, CHAIR, SIDEBOARD]),
    RoomCase("dining-04", "大餐厅 4.0×4.5 · 长餐桌+餐椅×6", 4.0, 4.5, group="dining",
             furniture=[TABLE_BIG, CHAIR, CHAIR, CHAIR, CHAIR, CHAIR, CHAIR]),
    RoomCase("dining-05", "小餐厅 2.8×3.6 · 餐桌+餐椅×2（无餐边柜）", 2.8, 3.6, group="dining",
             furniture=[TABLE, CHAIR, CHAIR]),
    RoomCase("dining-06", "大餐厅 4.0×4.5 · 长餐桌+餐椅×6+餐边柜", 4.0, 4.5, group="dining",
             furniture=[TABLE_BIG, CHAIR, CHAIR, CHAIR, CHAIR, CHAIR, CHAIR, SIDEBOARD]),
]
