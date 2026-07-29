import re
from typing import Dict, Any, List, Optional

def parse_requirement(user_input: str) -> Dict[str, Any]:
    # Space type
    space_type = "未知空间"
    if "卧室" in user_input:
        space_type = "卧室"
    elif "客厅" in user_input:
        space_type = "客厅"
    elif "玄关" in user_input:
        space_type = "玄关"
    elif "餐厅" in user_input:
        space_type = "餐厅"

    # Style
    style = "现代简约"
    if "奶油风" in user_input:
        style = "奶油风"
    elif "原木风" in user_input:
        style = "原木风"
    elif "轻法式" in user_input:
        style = "轻法式"

    # Budget
    # Improved regex to handle "2万", "20000元" etc.
    budget_max = 0
    budget_match = re.search(r"(\d+(?:\.\d+)?)\s*([万|元])", user_input)
    if budget_match:
        val = float(budget_match.group(1))
        unit = budget_match.group(2)
        if unit == "万":
            budget_max = int(val * 10000)
        else:
            budget_max = int(val)
    
    budget_level = "中等预算"
    if budget_max > 0:
        if budget_max < 10000:
            budget_level = "经济型"
        elif budget_max > 50000:
            budget_level = "高端定制"

    # Area (New)
    area = 0
    area_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:平米|平方米|平|sqm|㎡)", user_input)
    if area_match:
        area = float(area_match.group(1))

    # Custom projects
    projects = []
    if "衣柜" in user_input:
        projects.append("衣柜")
    if "梳妆台" in user_input:
        projects.append("梳妆台")
    if "背景墙" in user_input:
        projects.append("床头背景墙" if space_type == "卧室" else "电视背景墙")
    if "收纳" in user_input:
        projects.append("储物柜")
    if "电视柜" in user_input:
        projects.append("电视柜")
    if "玄关柜" in user_input:
        projects.append("玄关柜")

    # Constraints
    constraints = []
    if "不拆墙" in user_input:
        constraints.append("不拆墙")
    if "不改水电" in user_input:
        constraints.append("不改水电")

    # Goals
    goals = []
    if "收纳" in user_input:
        goals.append("增加收纳")
    if not goals:
        goals.append("提升颜值")

    return {
        "space_type": space_type,
        "style": style,
        "area": area if area > 0 else None,
        "budget": {
            "max_budget": budget_max if budget_max > 0 else "未指定",
            "budget_level": budget_level
        },
        "custom_projects": projects,
        "constraints": constraints,
        "renovation_goals": goals,
        "risk_notes": ["需要现场测量后确认实际价格"]
    }

def calculate_quote(projects: List[str]) -> Dict[str, Any]:
    # Mock price rules
    prices = {
        "衣柜": 1200, # per sqm
        "梳妆台": 2500, # per unit
        "床头背景墙": 800, # per sqm
        "电视背景墙": 1500, # per sqm
        "储物柜": 1100, # per sqm
        "电视柜": 1600, # per meter
        "玄关柜": 1100, # per sqm
    }
    
    itemized = []
    total_min = 0
    total_max = 0
    
    for p in projects:
        unit_price = prices.get(p, 1000)
        # Mock quantity
        qty = 6 if "柜" in p else 1
        cost = unit_price * qty
        
        min_cost = int(cost * 0.8)
        max_cost = int(cost * 1.2)
        
        itemized.append({
            "project_name": p,
            "price_range": f"{min_cost} - {max_cost} 元",
            "unit": "㎡" if "柜" in p or "墙" in p else "项"
        })
        total_min += min_cost
        total_max += max_cost
        
    return {
        "itemized_quotes": itemized,
        "total_range": f"{total_min} - {total_max} 元",
        "disclaimer": "以上为 AI 预估价格，实际价格需根据现场测量、材料品牌、五金配置确认。"
    }

# ---------------------------------------------------------------- 模板方案（LLM 降级用）

_BUDGET_RANGE_MID = {
    "3 万以下": 25000,
    "3-8 万": 60000,
    "8-15 万": 110000,
    "15-30 万": 220000,
    "30 万以上": 380000,
}

_BREAKDOWN = [
    ("硬装", 40),
    ("定制柜", 25),
    ("家具", 20),
    ("软装", 10),
    ("灯具与智能设备", 5),
]


def _breakdown(budget: int) -> List[Dict[str, Any]]:
    return [
        {"name": name, "percent": pct, "amount": int(budget * pct / 100)}
        for name, pct in _BREAKDOWN
    ]


def _furniture(items: List[tuple]) -> List[Dict[str, Any]]:
    result = []
    for i, (name, category, room, style, material, price, size, reason, alt) in enumerate(items):
        result.append(
            {
                "id": f"tf{i + 1}",
                "name": name,
                "category": category,
                "room": room,
                "style": style,
                "material": material,
                "priceRange": price,
                "sizeSuggestion": size,
                "matchScore": 96 - i * 2,
                "reason": reason,
                "alternative": alt,
            }
        )
    return result


def build_template_plans(requirement: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """确定性模板方案：结构与前端 DesignPlan 对齐，预算按用户所选区间缩放。"""
    requirement = requirement or {}
    base = _BUDGET_RANGE_MID.get(str(requirement.get("budgetRange", "")), 86000)

    plan_a_budget = base
    plan_b_budget = int(base * 0.84)
    plan_c_budget = int(base * 1.48)

    return [
        {
            "id": "plan-a",
            "name": "暖居 · 奶油原木风",
            "style": "奶油原木风",
            "score": 98,
            "budget": plan_a_budget,
            "tags": ["奶油白", "原木", "高收纳", "柔和灯光"],
            "suitableFor": ["小家庭", "宠物家庭", "喜欢温馨感"],
            "description": "以奶油白为主色，搭配浅木色家具和低饱和软装，营造温暖、放松、耐看的居住氛围。整屋以收纳为骨架、灯光为氛围。",
            "layoutSuggestions": [
                "客厅采用开放式布局，减少视觉阻隔，让采光贯穿全屋",
                "沙发靠墙摆放，释放中间活动空间",
                "电视墙结合整面收纳柜，提高空间利用率",
                "餐厅与客厅保持视觉连贯，使用同色系家具统一风格",
                "玄关增加顶天立地柜，进门动线上解决鞋帽收纳",
            ],
            "furnitureSuggestions": _furniture([
                ("云朵感三人位布艺沙发", "沙发", "客厅", "奶油风", "棉麻布艺", "¥4,800 - 7,200", "宽 2.2 - 2.4m", "低饱和奶油色与整体色调呼应，坐感松弛", "科技布沙发（更耐宠物抓挠）"),
                ("原木圆角茶几", "茶几", "客厅", "原木风", "白蜡木", "¥1,200 - 2,000", "直径 0.8 - 0.9m", "圆角对儿童友好，木纹自然", "岩板小边几组合（更易清洁）"),
                ("奶油白电视收纳柜", "柜子", "客厅", "奶油风", "实木颗粒板", "¥3,600 - 5,400", "整墙定制，深度 35cm", "整面收纳提高空间利用率", "半开放格栅电视柜"),
                ("多功能餐边柜", "柜子", "餐厅", "奶油风", "实木框架 + 长虹玻璃", "¥2,200 - 3,800", "宽 1.2 - 1.6m", "集收纳、水吧、展示于一体", "嵌入式餐边柜"),
                ("低饱和几何地毯", "地毯", "客厅", "北欧风", "混纺短绒", "¥900 - 1,600", "2m x 2.9m", "界定客厅区域，短绒方便打理", "羊毛平织地毯"),
            ]),
            "colorPalette": [
                {"name": "奶油白", "hex": "#F5EFE3", "usage": "墙面"},
                {"name": "浅木色", "hex": "#D2B48C", "usage": "柜体"},
                {"name": "暖灰色", "hex": "#B8B0A4", "usage": "沙发"},
                {"name": "亚麻米色", "hex": "#E8DFCA", "usage": "窗帘"},
                {"name": "鼠尾草绿", "hex": "#9CAF88", "usage": "点缀色"},
            ],
            "materials": [
                {"name": "木饰面", "description": "墙面与柜体过渡自然，增加温润感"},
                {"name": "棉麻布艺", "description": "沙发与窗帘主材，亲肤透气"},
                {"name": "微水泥", "description": "局部地面与台面，耐磨易打理"},
                {"name": "哑光金属", "description": "灯具与五金点缀，克制的精致感"},
            ],
            "lightingSuggestions": [
                {"name": "无主灯筒灯", "purpose": "基础照明", "description": "4000K 均匀铺光，天花更干净"},
                {"name": "柜体灯带", "purpose": "氛围照明", "description": "藏于收纳柜与吊顶，拉出空间层次"},
                {"name": "落地灯", "purpose": "局部照明", "description": "沙发阅读角的暖光补充"},
                {"name": "餐桌吊灯", "purpose": "功能照明", "description": "离桌面 75cm，聚拢用餐氛围"},
            ],
            "budgetBreakdown": _breakdown(plan_a_budget),
            "aiTips": [
                "如果希望进一步降低预算，可以优先减少木饰面上墙的面积，用乳胶漆同色替代。",
                "家中有儿童时，建议茶几与柜体边角采用圆角设计。",
                "有宠物的家庭，建议选择耐抓、易清洁的科技布沙发面料。",
            ],
        },
        {
            "id": "plan-b",
            "name": "留白 · 现代简约风",
            "style": "现代简约风",
            "score": 93,
            "budget": plan_b_budget,
            "tags": ["暖灰", "简洁线条", "隐藏收纳", "模块家具"],
            "suitableFor": ["预算控制", "喜欢干净利落空间", "小户型"],
            "description": "用暖灰与米白构建安静的底色，减少造型、强调线条与留白。收纳全部隐入墙面，预算集中花在每天都摸得到的地方。",
            "layoutSuggestions": [
                "取消复杂吊顶，用无主灯设计保持天花简洁",
                "定制柜全部通顶且与墙面同色，视觉上「消失」",
                "选用模块化沙发，未来调整布局可重新组合",
                "走廊尽头设置端景，让动线有视觉落点",
            ],
            "furnitureSuggestions": _furniture([
                ("模块布艺沙发", "沙发", "客厅", "现代简约", "科技布", "¥3,800 - 6,000", "三人位 + 脚凳", "可重组适应不同布局", "皮质沙发（质感更强）"),
                ("圆形岩板餐桌", "餐桌", "餐厅", "轻奢风", "岩板 + 碳素钢", "¥2,800 - 4,600", "直径 1.2 - 1.35m", "圆桌动线灵活，岩板耐用零维护", "实木原色餐桌"),
                ("白蜡木升降书桌", "书桌", "书房", "现代简约", "白蜡木", "¥2,400 - 3,900", "1.4m x 0.7m", "居家办公可站可坐更护腰", "固定实木长桌"),
                ("暖光落地灯", "灯具", "客厅", "现代简约", "金属 + 布艺灯罩", "¥560 - 980", "高 1.5 - 1.6m", "3000K 暖光补充角落氛围", "可调色温阅读灯"),
                ("低饱和几何地毯", "地毯", "客厅", "北欧风", "混纺短绒", "¥900 - 1,600", "2m x 2.9m", "柔化大面积硬质表面", "羊毛平织地毯"),
            ]),
            "colorPalette": [
                {"name": "米白", "hex": "#F2EFE9", "usage": "墙面"},
                {"name": "暖灰", "hex": "#C7C1B6", "usage": "柜体"},
                {"name": "浅咖", "hex": "#A89880", "usage": "沙发"},
                {"name": "燕麦色", "hex": "#E5DED2", "usage": "窗帘"},
                {"name": "哑黑", "hex": "#4A4741", "usage": "点缀色"},
            ],
            "materials": [
                {"name": "哑光烤漆板", "description": "柜体门板，纯净利落不反光"},
                {"name": "岩板", "description": "台面与餐桌，耐用零维护"},
                {"name": "短绒地毯", "description": "柔化大面积硬质表面"},
                {"name": "细框金属", "description": "灯具与门框线条，克制的工业感"},
            ],
            "lightingSuggestions": [
                {"name": "磁吸轨道灯", "purpose": "基础照明", "description": "灯位可随家具布局调整"},
                {"name": "窗帘盒灯带", "purpose": "氛围照明", "description": "夜晚模拟自然光洗墙"},
                {"name": "壁灯", "purpose": "局部照明", "description": "床头与走廊，替代台灯"},
                {"name": "感应地脚灯", "purpose": "功能照明", "description": "夜间起夜的柔和指引"},
            ],
            "budgetBreakdown": _breakdown(plan_b_budget),
            "aiTips": [
                "简约风格对施工平整度要求更高，墙面基层处理不要压缩预算。",
                "全屋同色系时，可通过材质差异（布艺 / 木 / 金属）避免单调。",
                "若经常在家办公，建议为书桌区单独增加 4000K 功能照明。",
            ],
        },
        {
            "id": "plan-c",
            "name": "微醺 · 轻奢质感风",
            "style": "轻奢质感风",
            "score": 89,
            "budget": plan_c_budget,
            "tags": ["石材", "金属", "皮革", "氛围灯"],
            "suitableFor": ["追求品质感", "大户型", "注重材质"],
            "description": "以暖调石材与皮革构建质感基底，金属线条勾勒轮廓，层次丰富的灯光让夜晚的家像一间安静的酒店大堂。",
            "layoutSuggestions": [
                "客厅采用对称式布局，强化仪式感与秩序感",
                "沙发区下沉式地毯界定，搭配双侧边几",
                "背景墙采用大板岩板 + 灯带悬浮设计",
                "餐厅设置整面酒柜 / 展示柜，玻璃门内藏灯",
            ],
            "furnitureSuggestions": _furniture([
                ("头层皮革三人沙发", "沙发", "客厅", "轻奢风", "头层皮革", "¥8,800 - 14,000", "宽 2.4 - 2.6m", "随使用愈发温润，质感突出", "绒布沙发（更适合宠物家庭）"),
                ("圆形岩板餐桌", "餐桌", "餐厅", "轻奢风", "岩板 + 碳素钢", "¥2,800 - 4,600", "直径 1.35m", "岩板耐高温易清洁", "大理石餐桌（纹理更自然）"),
                ("鼠尾草绿单人休闲椅", "沙发", "卧室", "中古风", "绒布 + 实木脚", "¥1,500 - 2,400", "宽 0.75m", "一抹低饱和绿打破米色的单调", "藤编休闲椅"),
                ("分子吊灯", "灯具", "客厅", "轻奢风", "黄铜 + 玻璃", "¥1,800 - 3,200", "直径 1m 左右", "客厅视觉中心，兼顾造型与照明", "线性吊灯（更简洁）"),
                ("多功能餐边酒柜", "柜子", "餐厅", "轻奢风", "实木框架 + 玻璃", "¥3,500 - 6,000", "整墙定制", "展示层板重点打光，仪式感强", "嵌入式酒柜"),
            ]),
            "colorPalette": [
                {"name": "暖白", "hex": "#F1ECE4", "usage": "墙面"},
                {"name": "浅驼色", "hex": "#C9AE8F", "usage": "柜体"},
                {"name": "焦糖棕", "hex": "#9C6B45", "usage": "沙发"},
                {"name": "香槟金", "hex": "#CDB287", "usage": "点缀色"},
                {"name": "墨绿", "hex": "#3F5548", "usage": "背景墙"},
            ],
            "materials": [
                {"name": "大板岩板", "description": "背景墙与台面，大气整面无拼缝"},
                {"name": "头层皮革", "description": "沙发与单椅，随使用愈发温润"},
                {"name": "拉丝黄铜", "description": "灯具、五金与家具脚的金色线条"},
                {"name": "绒布", "description": "窗帘与抱枕，浓郁的垂坠感"},
            ],
            "lightingSuggestions": [
                {"name": "分子吊灯", "purpose": "基础照明", "description": "客厅视觉中心，兼顾造型"},
                {"name": "洗墙灯带", "purpose": "氛围照明", "description": "突出石材与木饰面的肌理"},
                {"name": "床头吊线灯", "purpose": "局部照明", "description": "取代台灯，释放床头柜台面"},
                {"name": "酒柜射灯", "purpose": "功能照明", "description": "展示层板重点打光"},
            ],
            "budgetBreakdown": _breakdown(plan_c_budget),
            "aiTips": [
                "如果希望降低预算，可优先减少石材与复杂吊顶，保留灯光设计即可保住氛围。",
                "皮革家具在有宠物的家庭中易留抓痕，可局部替换为绒布或科技布。",
                "轻奢风格建议控制金属点缀的比例在 10% 以内，避免显「金」。",
            ],
        },
    ]


def generate_report(requirement: Dict[str, Any], quote: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": f"{requirement['space_type']}装修定制需求单",
        "summary": f"基于{requirement['style']}风格的改造方案，重点关注{', '.join(requirement['custom_projects'])}。",
        "sections": [
            {
                "name": "核心需求",
                "content": requirement
            },
            {
                "name": "预算预估",
                "content": quote
            },
            {
                "name": "改造建议",
                "content": [
                    "建议采用通体顶天立地柜体以最大化收纳空间",
                    "风格统一采用浅色系以提升空间感"
                ]
            }
        ]
    }
