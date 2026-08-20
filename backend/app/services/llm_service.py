"""DeepSeek LLM 服务层。

所有函数遵循同一原则：LLM 可用时走真实模型，失败/未配置时抛出 LLMUnavailable，
由调用方决定降级策略（规则解析 / 模板方案 / 前端本地回复）。
"""

import base64
import json
import logging
from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    pass


_client: Optional[OpenAI] = None
_vl_client: Optional[OpenAI] = None

# 最近一次 generate_plans 的完整生成元数据（模型/Prompt/输入/用量/成本）。
# 由 generate_plans 成功调用后更新，tasks 层在 workflow.run 之后读取落库。
_last_generation_meta: Optional[Dict[str, Any]] = None


def last_generation_meta() -> Optional[Dict[str, Any]]:
    """返回最近一次方案生成的元数据；无则为 None。"""
    return _last_generation_meta


def estimate_cost_cny(
    usage: Optional[Dict[str, Any]],
    input_price_per_mtok: Optional[float],
    output_price_per_mtok: Optional[float],
) -> Optional[float]:
    """按 token 用量估算成本（元）；单价缺失或用量缺失时返回 None。"""
    if not usage or input_price_per_mtok is None or output_price_per_mtok is None:
        return None
    prompt_tokens = usage.get("prompt_tokens") or 0
    completion_tokens = usage.get("completion_tokens") or 0
    if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
        return None
    return round(
        (prompt_tokens * input_price_per_mtok
         + completion_tokens * output_price_per_mtok)
        / 1_000_000,
        6,
    )


def get_client() -> OpenAI:
    global _client
    if not settings.llm_api_key:
        raise LLMUnavailable("LLM_API_KEY 未配置")
    if _client is None:
        _client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=120,
        )
    return _client


def get_vl_client() -> OpenAI:
    global _vl_client
    if not settings.vl_api_key:
        raise LLMUnavailable("VL_API_KEY 未配置")
    if _vl_client is None:
        _vl_client = OpenAI(
            api_key=settings.vl_api_key,
            base_url=settings.vl_base_url,
            timeout=120,
        )
    return _vl_client


def _chat_json(
    system: str,
    user: str,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    usage_out: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """调用 DeepSeek 并解析 JSON 输出。usage_out 传入时写入 token 用量。"""
    try:
        resp = get_client().chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if usage_out is not None and resp.usage is not None:
            usage_out.update(
                {
                    "prompt_tokens": resp.usage.prompt_tokens,
                    "completion_tokens": resp.usage.completion_tokens,
                    "total_tokens": resp.usage.total_tokens,
                }
            )
        return json.loads(resp.choices[0].message.content)
    except LLMUnavailable:
        raise
    except Exception as exc:  # 网络、限流、JSON 解析失败等统一降级
        logger.warning("LLM 调用失败: %s", exc)
        raise LLMUnavailable(str(exc)) from exc


# ---------------------------------------------------------------- 需求解析

_PARSE_SYSTEM = """你是家装需求分析师。从用户的装修描述中提取结构化信息，输出 JSON：
{
  "space_type": "客厅/卧室/玄关/餐厅/全屋/未知空间",
  "style": "奶油风/原木风/现代简约/轻法式/... 未提及则给出最合理推测",
  "area": 数字或 null,
  "budget": {"max_budget": 数字或"未指定", "budget_level": "经济型/中等预算/高端定制"},
  "custom_projects": ["定制项目，如 衣柜/电视背景墙/玄关柜"],
  "constraints": ["硬性限制，如 不拆墙/不改水电"],
  "renovation_goals": ["装修目标，如 增加收纳/提升颜值"],
  "risk_notes": ["需要提醒用户的风险点"],
  "missing_fields": ["缺失的关键信息字段名，如 budget/area"],
  "follow_up_questions": ["针对缺失信息的追问，中文，口语化"]
}
只输出 JSON。"""


def parse_requirement(user_input: str) -> Dict[str, Any]:
    """LLM 需求解析；失败时抛 LLMUnavailable，由调用方降级到规则解析。"""
    return _chat_json(_PARSE_SYSTEM, user_input, max_tokens=1500)


# ---------------------------------------------------------------- 对话确认

_CHAT_SYSTEM = """你是「AI 家装定制助手」的资深室内设计师，正在和业主确认装修需求。
风格要求：
- 中文回复，口语化、温暖、专业，像面对面聊天的设计师
- 每次回复 2-4 句话，先回应用户的诉求，再给出具体可落地的设计建议
- 涉及预算时给出大致比例或百分比，涉及材质给出具体材料名
- 不要用列表和标题，用自然段落
- 结尾可以自然地引导用户补充其他需求，但不要每次都问问题"""


def chat_reply(
    message: str,
    history: Optional[List[Dict[str, str]]] = None,
    requirement: Optional[Dict[str, Any]] = None,
) -> str:
    """对话式需求确认。history 为 [{role: user|assistant, content}]。"""
    messages: List[Dict[str, str]] = [{"role": "system", "content": _CHAT_SYSTEM}]
    if requirement:
        messages.append(
            {
                "role": "system",
                "content": "业主已填写的需求表单：" + json.dumps(requirement, ensure_ascii=False),
            }
        )
    for item in (history or [])[-8:]:  # 只带最近 8 条，控制上下文长度
        role = "assistant" if item.get("role") in ("ai", "assistant") else "user"
        messages.append({"role": role, "content": item.get("content", "")})
    messages.append({"role": "user", "content": message})

    try:
        resp = get_client().chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            max_tokens=500,
            temperature=0.8,
        )
        return resp.choices[0].message.content.strip()
    except LLMUnavailable:
        raise
    except Exception as exc:
        logger.warning("LLM 对话失败: %s", exc)
        raise LLMUnavailable(str(exc)) from exc


# ---------------------------------------------------------------- 方案生成

_PLAN_SYSTEM = """你是资深室内设计师。根据业主需求生成 3 套风格差异明显的家装方案，输出 JSON：
{"plans": [方案1, 方案2, 方案3]}

每套方案的结构（所有文案用中文，价格用人民币整数）：
{
  "id": "plan-a",                     // 依次为 plan-a / plan-b / plan-c
  "name": "两个字意境词 · 风格名",      // 例如 "暖居 · 奶油原木风"
  "style": "风格名",
  "score": 85-99 的整数,               // 与业主需求的匹配度，第一套最高
  "budget": 总预算整数,                // 必须贴合业主预算范围，三套有梯度
  "tags": ["4 个关键词"],
  "suitableFor": ["3 类适合人群"],
  "description": "60 字以内的方案综述，落到居住感受",
  "layoutSuggestions": ["恰好 4 条布局建议，每条 25 字以内"],
  "furnitureSuggestions": [            // 恰好 4 件，必须从用户消息的【本店成品家具库】中选择
    {"sku": "库中的 sku，一字不差", "name": "库中名称", "quantity": 1,
     "reason": "结合业主生活方式的推荐理由，25 字以内",
     "alternative": "库内替代款或说明，15 字以内"}
  ],
  "customItems": [                     // 2-4 项，从【本店定制项目价目表】中选，估算工程量
    {"project": "价目表中的项目名", "grade": "价目表中的材料档位",
     "quantity": 6.5, "note": "工程量估算依据，如：主卧衣柜投影约6.5㎡"}
  ],
  "colorPalette": [                    // 恰好 5 个
    {"name": "颜色名", "hex": "#XXXXXX", "usage": "墙面/柜体/沙发/窗帘/点缀色"}
  ],
  "materials": [                       // 恰好 4 个
    {"name": "材质名", "description": "20 字以内，说明用在哪里"}
  ],
  "lightingSuggestions": [             // 恰好 4 个
    {"name": "灯具名", "purpose": "基础照明/氛围照明/局部照明/功能照明", "description": "15 字以内"}
  ],
  "budgetBreakdown": [                 // 恰好 5 项，percent 合计 100，amount = budget * percent / 100
    {"name": "硬装", "percent": 40, "amount": 数字},
    {"name": "定制柜", "percent": 25, "amount": 数字},
    {"name": "家具", "percent": 20, "amount": 数字},
    {"name": "软装", "percent": 10, "amount": 数字},
    {"name": "灯具与智能设备", "percent": 5, "amount": 数字}
  ],
  "aiTips": ["恰好 3 条针对业主家庭情况的优化建议，每条 30 字以内"]
}

要求：
- 三套方案风格必须不同，优先覆盖业主选择的风格
- 家具的 sku 和定制项目的 project/grade 必须与商品库/价目表完全一致，禁止编造库中不存在的商品和价格
- 家具按风格与业主需求匹配着选：不同方案尽量选不同的家具组合
- 定制项目的工程量(quantity)要结合房屋面积和空间合理估算
- 有孩子/宠物/老人时，家具和材质建议必须体现对应的安全、易清洁、适老考虑
- 如果业主需求中包含 profile_context（业主长期画像），方案必须贴合画像中的预算、风格、家庭结构、生活方式与软性偏好
- budgetBreakdown 的 percent 每套可以不同，但合计必须是 100
- 严格控制字数上限，输出紧凑的 JSON（不要缩进和换行）
只输出 JSON。"""


_PLAN_REQUIRED_KEYS = (
    "name",
    "style",
    "budget",
    "furnitureSuggestions",
    "colorPalette",
    "budgetBreakdown",
)


def _normalize_plans(plans: List[Any]) -> List[Dict[str, Any]]:
    """规整 LLM 输出：过滤残缺方案、截取前 3 套、统一 id 与关键字段兜底。"""
    valid: List[Dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        if not all(plan.get(k) for k in _PLAN_REQUIRED_KEYS):
            continue
        valid.append(plan)

    valid = valid[:3]
    for i, plan in enumerate(valid):
        plan["id"] = f"plan-{chr(ord('a') + i)}"
        plan.setdefault("score", 95 - i * 4)
        plan.setdefault("tags", [])
        plan.setdefault("suitableFor", [])
        plan.setdefault("description", "")
        plan.setdefault("layoutSuggestions", [])
        plan.setdefault("materials", [])
        plan.setdefault("lightingSuggestions", [])
        plan.setdefault("aiTips", [])
        try:
            plan["budget"] = int(plan["budget"])
        except (TypeError, ValueError):
            plan["budget"] = 0
    return valid


def generate_plans(
    requirement: Dict[str, Any], catalog_context: Optional[str] = None
) -> List[Dict[str, Any]]:
    """根据结构化需求生成 3 套方案；失败时抛 LLMUnavailable，调用方降级到模板方案。

    catalog_context：商品库 + 定制价目表文本，提供时家具与定制项只能从中选择。
    成功后把模型 / Prompt / 输入 / 用量 / 成本记录到 last_generation_meta()。
    """
    global _last_generation_meta
    _last_generation_meta = None  # 每次调用先清空，避免降级时残留上次的元数据

    user = "业主需求：" + json.dumps(requirement, ensure_ascii=False)
    if catalog_context:
        user += "\n\n" + catalog_context
    usage: Dict[str, Any] = {}
    data = _chat_json(_PLAN_SYSTEM, user, max_tokens=8192, usage_out=usage)
    raw_plans = data.get("plans")
    if not isinstance(raw_plans, list):
        raise LLMUnavailable("LLM 返回的方案结构不完整")
    plans = _normalize_plans(raw_plans)
    # 至少要有 2 套结构完整的方案才算成功，否则降级模板
    if len(plans) < 2:
        raise LLMUnavailable(f"LLM 有效方案不足（{len(plans)} 套）")

    _last_generation_meta = {
        "model": settings.llm_model,
        "prompt_snapshot": (_PLAN_SYSTEM + "\n\n" + user)[:8000],
        "input_snapshot": {
            "requirement": requirement,
            "has_catalog_context": bool(catalog_context),
        },
        "usage": usage or None,
        "cost_cny": estimate_cost_cny(
            usage or None,
            settings.llm_input_price_per_mtok,
            settings.llm_output_price_per_mtok,
        ),
    }
    return plans


# ---------------------------------------------------------------- 方案精修（Refine）

_REFINE_SYSTEM = """你是资深室内设计师。根据业主的修改指令，在现有方案基础上做精准修改。
输出 JSON：{"plan": {...修改后的完整方案...}, "message": "一句话说明改了什么，30 字以内"}

修改规则：
- 只改业主明确要求的部分，其余字段保持原样；方案的 id 绝对保持不变
- 换家具时 furnitureSuggestions 的 sku 必须从【本店成品家具库】中选择，禁止编造库中不存在的商品
- 定制项目 project/grade 必须从【本店定制项目价目表】中选择
- 涉及预算调整时，通过更换更便宜/更贵的商品、调整定制工程量来实现，而不是凭空改数字
- budgetBreakdown 的 percent 合计必须 100，amount 与 budget 对应
- 方案结构与原方案完全一致（name/style/budget/tags/description/layoutSuggestions/
  furnitureSuggestions/customItems/colorPalette/materials/lightingSuggestions/budgetBreakdown/aiTips）
- 严格控制字数，输出紧凑 JSON（不要缩进和换行）
只输出 JSON。"""


def refine_plan(
    plan: Dict[str, Any],
    instruction: str,
    catalog_context: Optional[str] = None,
) -> tuple[Dict[str, Any], str]:
    """在现有方案基础上按指令精准修改；失败时抛 LLMUnavailable。

    返回 (修改后的方案, 一句话说明)。方案 id 由调用方保持与入参一致。
    """
    user = "当前方案：" + json.dumps(plan, ensure_ascii=False)
    user += "\n\n修改指令：" + instruction
    if catalog_context:
        user += "\n\n" + catalog_context
    data = _chat_json(_REFINE_SYSTEM, user, max_tokens=8192)
    plan_data = data.get("plan")
    if not isinstance(plan_data, dict) or not plan_data.get("name"):
        raise LLMUnavailable("方案修改返回结构不完整")
    plan_data["id"] = plan.get("id")
    return plan_data, str(data.get("message") or "")


# ---------------------------------------------------------------- 用户画像提取

_EXTRACT_PROFILE_SYSTEM = """你是家装用户画像分析师。从用户提供的文本（需求描述/对话/修改指令）中提取装修偏好。
输出 JSON：
{
  "budget_min": 数字或 null,
  "budget_max": 数字或 null,
  "preferred_styles": ["标准风格名"],
  "facts": {
    "family_structure": "家庭结构描述，如 三口之家有个5岁孩子，没有则 null",
    "lifestyle": ["生活方式关键词，如 在家办公/养宠物"],
    "space_layout": {"rooms": ["空间"], "area": 数字或 null},
    "renovation_goals": ["装修目标，如 增加收纳"],
    "constraints": ["硬性限制，如 不拆墙"],
    "soft_preferences": ["软性偏好，如 喜欢木质元素"]
  }
}
要求：
- 只提取文本中明确提到的信息，不确定的用 null 或空数组，禁止编造
- 预算单位是元：用户说"15 万"则换算成 150000
- preferred_styles 用标准风格名（奶油风/原木风/现代简约/轻法式/中古风等）
只输出 JSON。"""


def extract_profile(text: str) -> Dict[str, Any]:
    """从文本提取用户装修画像；失败时抛 LLMUnavailable，由调用方静默跳过。"""
    return _chat_json(_EXTRACT_PROFILE_SYSTEM, text, max_tokens=1500)


# ---------------------------------------------------------------- 需求级指标评判

_JUDGE_COMPLIANCE_SYSTEM = """你是家装方案评审员。判断方案是否遵守业主的硬性约束（constraints）。
输出 JSON：{"compliant": true/false, "reason": "一句话说明，30 字以内"}
判断标准：
- 方案只要明确违反任意一条硬性约束即为 false
- 约束没被方案提及（无法判断）时，默认视为遵守（true），不要臆测
只输出 JSON。"""


def judge_plan_compliance(
    requirement: Dict[str, Any],
    plan_text: str,
) -> tuple[bool, str]:
    """用 LLM 判断方案是否遵守需求中的硬性约束。失败时抛 LLMUnavailable。

    用于需求级评测（约束遵守率），不参与线上主流程。
    """
    constraints = requirement.get("constraints") or []
    if not constraints:
        return True, "无硬性约束"
    user = (
        "业主硬性约束：" + json.dumps(constraints, ensure_ascii=False)
        + "\n\n方案内容：" + plan_text
    )
    data = _chat_json(_JUDGE_COMPLIANCE_SYSTEM, user, max_tokens=500)
    compliant = bool(data.get("compliant"))
    return compliant, str(data.get("reason") or "")


# ---------------------------------------------------------------- Scene Agent

_SCENE_AGENT_SYSTEM = """你是坐标计算器。必须执行明确指令，禁止追问。
输出 JSON 且 operations 不能为空，只允许 move、rotate、remove、add，最多12项。
move/rotate/remove 只能使用 scene 已有 instanceId；add 只能使用 catalog 已有 sku。
左=x减小，右=x增加，前=z增加，后=z减小；厘米除以100换算成米。
move 输出绝对 position{x,z}，rotate 输出绝对 rotationY，不能输出Y坐标或代码。
示例：sofa-main 当前 x=0,z=-1，向左移动30厘米，应输出
{"message":"已移动","operations":[{"type":"move","instanceId":"sofa-main","position":{"x":-0.3,"z":-1}}]}。
只输出 JSON。"""


def plan_scene_operations(
    *,
    instruction: str,
    context: Dict[str, Any],
):
    """把自然语言转换为受 Pydantic 鉴别联合约束的场景操作。"""
    from app.schemas.scene_agent import SceneOperationBatch

    user_prompt = (
        "指令："
        + instruction
        + "\n数据："
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )
    data = _chat_json(
        _SCENE_AGENT_SYSTEM,
        user_prompt,
        max_tokens=2000,
        temperature=0.2,
    )
    if isinstance(data.get("operations"), list) and not data["operations"]:
        data = _chat_json(
            _SCENE_AGENT_SYSTEM,
            user_prompt
            + "\n\n上一次返回了空 operations。该指令信息充分，请严格按坐标约定"
            "计算至少一个白名单操作；不要返回解释性空结果。",
            max_tokens=2000,
            temperature=0.1,
        )
    try:
        return SceneOperationBatch.model_validate(data)
    except Exception as exc:
        raise LLMUnavailable("Scene Agent 返回的操作结构无效") from exc


# ---------------------------------------------------------------- 图片分析（Qwen3-VL）

_IMAGE_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}

_VL_FLOORPLAN_SYSTEM = """你是家装空间分析师，正在看用户上传的户型图或房间照片。
请识别空间信息并输出 JSON：
{
  "image_kind": "floor_plan（户型图）/ room_photo（房间照片）/ other",
  "space_type": "识别到的主要空间，如 客厅/卧室/全屋，无法判断则 未知空间",
  "room_count": "房间数量描述，如 三室两厅一厨两卫，无法判断则空字符串",
  "findings": ["4-6 条具体、可落地的空间观察，每条 25 字以内，聚焦采光、动线、收纳、结构、可改造点"],
  "suggestions": ["2-3 条针对该空间的装修建议，每条 25 字以内"]
}
要求：findings 必须基于图片真实内容，不要编造具体面积数字（除非图上明确标注）。只输出 JSON。"""


def analyze_image(image_bytes: bytes, file_name: str) -> Dict[str, Any]:
    """用 Qwen3-VL 分析户型图/房间照片，返回结构化结果。

    失败时抛 LLMUnavailable，由调用方降级到占位结果。
    """
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "png"
    mime = _IMAGE_MIME.get(ext, "image/png")
    b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:{mime};base64,{b64}"

    try:
        resp = get_vl_client().chat.completions.create(
            model=settings.vl_model,
            messages=[
                {"role": "system", "content": _VL_FLOORPLAN_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请分析这张图片。"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=1000,
            temperature=0.4,
        )
        data = json.loads(resp.choices[0].message.content)
        if not data.get("findings"):
            raise LLMUnavailable("VL 返回结果缺少 findings")
        return data
    except LLMUnavailable:
        raise
    except Exception as exc:
        logger.warning("VL 图片分析失败: %s", exc)
        raise LLMUnavailable(str(exc)) from exc


_PLACEHOLDER_FINDINGS = [
    "已接收图片，AI 空间识别服务暂不可用",
    "可继续与设计师对话补充空间信息",
    "建议在需求中说明户型、朝向与主要空间",
]


def placeholder_image_analysis() -> Dict[str, Any]:
    """VL 不可用时的降级结果。"""
    return {
        "image_kind": "other",
        "space_type": "未知空间",
        "room_count": "",
        "findings": _PLACEHOLDER_FINDINGS,
        "suggestions": [],
    }


# ---------------------------------------------------------------- RoomModel 空间识别

_VL_ROOM_MODEL_SYSTEM = """你是家装空间分析师，正在看用户上传的户型图或房间照片。
请把图片中的空间信息结构化成统一空间事实模型，输出 JSON（字段名用 camelCase）：

{
  "imageKind": "floor_plan（户型图）/ room_photo（房间照片）/ other",
  "spaceType": "识别到的主要空间，如 客厅/卧室/全屋，无法判断则 未知空间",
  "roomCount": "户型文字描述，如 三室两厅一厨两卫，无法判断则空字符串",
  "rooms": [
    {"id": "living-room", "name": "客厅",
     "floorPolygon": [{"x":0.05,"z":0.05},{"x":0.95,"z":0.05},{"x":0.95,"z":0.6},{"x":0.05,"z":0.6}],
     "ceilingHeight": null, "confidence": 0.8}
  ],
  "walls": [{"roomId":"living-room","wallIndex":0,"loadBearing":null,"confidence":0.6}],
  "doors": [{"id":"door-1","roomId":"living-room","type":"door","wallIndex":0,
             "offset":0.4,"width":0.12,"height":2.1,"sillHeight":0,"confidence":0.7}],
  "windows": [{"id":"win-1","roomId":"living-room","type":"window","wallIndex":2,
               "offset":0.3,"width":0.35,"height":1.5,"sillHeight":0.9,"confidence":0.7}],
  "fixedObstacles": [{"name":"承重柱","roomId":"living-room","confidence":0.5}],
  "existingFurniture": [{"name":"布艺沙发","category":"沙发","roomId":"living-room","confidence":0.6}],
  "scale": {"source":"default","referenceWallLength":null,
            "referenceRoomId":null,"referenceWallIndex":null,"confidence":0.3},
  "confidence": 0.6,
  "requiresConfirmation": ["roomDimensions","doorWidth","windowSize"],
  "analysisNotes": ["4-6 条具体空间观察，每条 25 字以内，聚焦采光、动线、收纳、结构"],
  "suggestions": ["2-3 条装修建议，每条 25 字以内"]
}

要求：
- floorPolygon 用归一化坐标（0~1），至少 3 个顶点，按顺时针或逆时针连续排列；顶点即墙体，边即墙
- 绝对尺寸（真实米数）一律不猜：ceilingHeight、门窗 height、referenceWallLength 无法确定时设为 null，
  并把对应项加入 requiresConfirmation
- 门窗用 roomId + wallIndex + offset(0~1，沿墙起点的比例) + width(0~1，占墙长比例) 描述
- 图片内容不够确定时，宁可降低 confidence、把字段加进 requiresConfirmation，也不要编造
- analysisNotes 必须基于图片真实内容，不要编造具体面积数字（除非图上明确标注）
只输出 JSON。"""


def analyze_room_model(image_bytes: bytes, file_name: str) -> Dict[str, Any] | None:
    """用 Qwen3-VL 输出统一空间事实模型 RoomModel（含文字观察）。

    返回 RoomModel 的 camelCase dict；VL 不可用抛 LLMUnavailable；
    输出不符合 Schema 时返回 None，由调用方降级为纯文字分析。
    """
    from app.schemas.room_model import RoomModel

    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "png"
    mime = _IMAGE_MIME.get(ext, "image/png")
    b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:{mime};base64,{b64}"

    try:
        resp = get_vl_client().chat.completions.create(
            model=settings.vl_model,
            messages=[
                {"role": "system", "content": _VL_ROOM_MODEL_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请分析这张图片的空间结构。"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=2000,
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content)
    except LLMUnavailable:
        raise
    except Exception as exc:
        logger.warning("VL 空间识别失败: %s", exc)
        raise LLMUnavailable(str(exc)) from exc

    try:
        model = RoomModel.model_validate(data)
    except Exception as exc:
        logger.warning("VL 返回的 RoomModel 结构无效，降级为纯文字分析: %s", exc)
        return None
    return model.model_dump(by_alias=True, mode="json")
