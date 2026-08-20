"""卧室评测案例：覆盖主卧/次卧/儿童房尺寸与床、衣柜、床头柜、梳妆台组合。"""

from evals.cases.base import RoomCase
from evals.cases.base import make_furniture as _f

BED = _f("BED-001", "标准双人床", "床", 1.8, 2.0, 0.5)
BED_BIG = _f("BED-002", "加大双人床", "床", 2.0, 2.2, 0.5)
BED_SINGLE = _f("BED-003", "单人床", "床", 1.2, 2.0, 0.5)
WARDROBE = _f("WARD-001", "通顶衣柜", "柜子", 1.8, 0.6, 2.2)
WARDROBE_SMALL = _f("WARD-002", "小衣柜", "柜子", 1.2, 0.55, 2.1)
NIGHTSTAND = _f("NIGHT-001", "床头柜", "床头柜", 0.5, 0.4, 0.5)
DRESSER = _f("DRESS-001", "梳妆台", "书桌", 1.0, 0.5, 0.75)
OFFICE_CHAIR = _f("CHAIR-OFFICE", "梳妆凳", "书椅", 0.45, 0.45, 0.5)

CASES: list[RoomCase] = [
    RoomCase("bedroom-01", "主卧 3.6×4.2 · 床+衣柜+床头柜×2", 3.6, 4.2, group="bedroom",
             furniture=[BED, WARDROBE, NIGHTSTAND, NIGHTSTAND]),
    RoomCase("bedroom-02", "主卧 4.0×5.0 · 床+衣柜+床头柜×2+梳妆台", 4.0, 5.0, group="bedroom",
             furniture=[BED_BIG, WARDROBE, NIGHTSTAND, NIGHTSTAND, DRESSER]),
    RoomCase("bedroom-03", "次卧 3.0×3.6 · 单人床+衣柜+床头柜", 3.0, 3.6, group="bedroom",
             furniture=[BED_SINGLE, WARDROBE_SMALL, NIGHTSTAND]),
    RoomCase("bedroom-04", "次卧 3.6×4.2 · 床+床头柜×2（无衣柜）", 3.6, 4.2, group="bedroom",
             furniture=[BED, NIGHTSTAND, NIGHTSTAND]),
    RoomCase("bedroom-05", "主卧 4.0×5.0 · 床+双衣柜+床头柜×2", 4.0, 5.0, group="bedroom",
             furniture=[BED_BIG, WARDROBE, WARDROBE, NIGHTSTAND, NIGHTSTAND]),
    RoomCase("bedroom-06", "儿童房 3.2×3.8 · 床+书桌+书椅", 3.2, 3.8, group="bedroom",
             furniture=[BED_SINGLE, DRESSER, OFFICE_CHAIR]),
    RoomCase("bedroom-07", "次卧 3.0×3.6 · 床+衣柜（紧凑）", 3.0, 3.6, group="bedroom",
             furniture=[BED_SINGLE, WARDROBE_SMALL]),
    RoomCase("bedroom-08", "主卧 3.6×4.2 · 床+衣柜+床头柜+梳妆台", 3.6, 4.2, group="bedroom",
             furniture=[BED, WARDROBE, NIGHTSTAND, DRESSER]),
]
