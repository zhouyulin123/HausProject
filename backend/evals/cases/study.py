"""书房评测案例：覆盖书桌、书椅与书柜组合及不同尺寸。"""

from evals.cases.base import RoomCase
from evals.cases.base import make_furniture as _f

DESK = _f("DESK-001", "标准书桌", "书桌", 1.4, 0.7, 0.75)
DESK_SMALL = _f("DESK-002", "小书桌", "书桌", 1.1, 0.6, 0.75)
OFFICE_CHAIR = _f("OFFICE-CHAIR-001", "办公椅", "书椅", 0.6, 0.6, 0.95)
BOOKCASE = _f("BOOKCASE-001", "书柜", "柜子", 0.9, 0.4, 2.0)
SIDE = _f("SIDE-001", "边柜", "柜子", 0.7, 0.4, 0.8)

CASES: list[RoomCase] = [
    RoomCase("study-01", "小书房 2.8×3.2 · 书桌+书椅", 2.8, 3.2, group="study",
             furniture=[DESK_SMALL, OFFICE_CHAIR]),
    RoomCase("study-02", "标准书房 3.0×3.6 · 书桌+书椅+书柜", 3.0, 3.6, group="study",
             furniture=[DESK, OFFICE_CHAIR, BOOKCASE]),
    RoomCase("study-03", "标准书房 3.6×4.2 · 书桌+书椅+书柜×2", 3.6, 4.2, group="study",
             furniture=[DESK, OFFICE_CHAIR, BOOKCASE, BOOKCASE]),
    RoomCase("study-04", "大书房 3.6×4.2 · 书桌+书椅+书柜+边柜", 3.6, 4.2, group="study",
             furniture=[DESK, OFFICE_CHAIR, BOOKCASE, SIDE]),
]
