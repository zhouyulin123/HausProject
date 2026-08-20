"""需求级评测用例：需求提取、约束遵守、预算偏差。

ground truth 由人工标注；run_requirement_eval.py 负责逐项打分。
"""

from dataclasses import dataclass, field


@dataclass
class RequirementCase:
    """需求提取准确率用例：输入自然语言 + 期望结构化字段。"""

    id: str
    name: str
    input: str
    expected: dict


@dataclass
class ConstraintCase:
    """约束遵守率用例：需求（含硬性约束）+ 方案文本 + 期望判定。"""

    id: str
    name: str
    requirement: dict
    plan_text: str
    expected_compliant: bool


@dataclass
class BudgetCase:
    """预算偏差率用例：预算范围 + 方案报价。"""

    id: str
    name: str
    budget_min: int
    budget_max: int
    plan_budget: int


REQUIREMENT_CASES: list[RequirementCase] = [
    RequirementCase(
        id="req-01",
        name="全屋·原木·儿童·不拆墙",
        input="我家90平三室两厅，想装原木风，预算15万，有个5岁的孩子，"
        "需要增加收纳，不拆墙不改水电。",
        expected={
            "space_type": "全屋",
            "style": "原木风",
            "area": 90,
            "budget_max": 150000,
            "constraints": ["不拆墙", "不改水电"],
            "custom_projects": ["储物柜"],
        },
    ),
    RequirementCase(
        id="req-02",
        name="客厅·奶油·软装",
        input="客厅想要奶油风，面积大概25平，预算3万，主要做软装，不改水电。",
        expected={
            "space_type": "客厅",
            "style": "奶油风",
            "area": 25,
            "budget_max": 30000,
            "constraints": ["不改水电"],
            "custom_projects": [],
        },
    ),
    RequirementCase(
        id="req-03",
        name="卧室·现代·整墙衣柜",
        input="主卧10平，现代简约，预算2万，做整面墙的衣柜。",
        expected={
            "space_type": "卧室",
            "style": "现代简约",
            "area": 10,
            "budget_max": 20000,
            "constraints": [],
            "custom_projects": ["衣柜"],
        },
    ),
    RequirementCase(
        id="req-04",
        name="餐厅·轻法式·餐边柜",
        input="餐厅轻法式风格，12平米，预算1万5，想要餐边柜和背景墙。",
        expected={
            "space_type": "餐厅",
            "style": "轻法式",
            "area": 12,
            "budget_max": 15000,
            "constraints": [],
            "custom_projects": ["餐边柜"],
        },
    ),
    RequirementCase(
        id="req-05",
        name="书房·原木·书柜收纳",
        input="书房8平米，原木风，预算8000元，重点是书柜收纳和一张大书桌。",
        expected={
            "space_type": "书房",
            "style": "原木风",
            "area": 8,
            "budget_max": 8000,
            "constraints": [],
            "custom_projects": ["书柜"],
        },
    ),
]

CONSTRAINT_CASES: list[ConstraintCase] = [
    ConstraintCase(
        id="cons-01",
        name="不拆墙但方案拆墙",
        requirement={"constraints": ["不拆墙", "不改水电"]},
        plan_text="建议打通客厅与阳台，拆除中间隔墙，让空间更通透。",
        expected_compliant=False,
    ),
    ConstraintCase(
        id="cons-02",
        name="不拆墙且方案未拆墙",
        requirement={"constraints": ["不拆墙"]},
        plan_text="保留原有墙体结构，通过软装和家具分区提升空间感。",
        expected_compliant=True,
    ),
    ConstraintCase(
        id="cons-03",
        name="儿童安全且方案圆角",
        requirement={"constraints": ["儿童安全"]},
        plan_text="家具全部采用圆角设计，避免尖锐边角，插座加装安全保护盖。",
        expected_compliant=True,
    ),
    ConstraintCase(
        id="cons-04",
        name="儿童安全但方案有玻璃尖角",
        requirement={"constraints": ["儿童安全"]},
        plan_text="选用大面积玻璃隔断与金属锐角边桌，突出现代感。",
        expected_compliant=False,
    ),
]

BUDGET_CASES: list[BudgetCase] = [
    BudgetCase(id="bud-01", name="预算内", budget_min=120000, budget_max=150000, plan_budget=138000),
    BudgetCase(id="bud-02", name="超预算20%", budget_min=120000, budget_max=150000, plan_budget=180000),
    BudgetCase(id="bud-03", name="低于预算", budget_min=120000, budget_max=150000, plan_budget=100000),
    BudgetCase(id="bud-04", name="正好上限", budget_min=120000, budget_max=150000, plan_budget=150000),
]
