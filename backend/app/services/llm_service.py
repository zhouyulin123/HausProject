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


def get_client() -> OpenAI:
    global _client
    if not settings.deepseek_api_key:
        raise LLMUnavailable("DEEPSEEK_API_KEY 未配置")
    if _client is None:
        _client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
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
            base_url=settings.vl_api_key_base_url,
            timeout=120,
        )
    return _vl_client


def _chat_json(
    system: str,
    user: str,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> Dict[str, Any]:
    """调用 DeepSeek 并解析 JSON 输出。"""
    try:
        resp = get_client().chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            temperature=temperature,
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
            model=settings.deepseek_model,
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
    """
    user = "业主需求：" + json.dumps(requirement, ensure_ascii=False)
    if catalog_context:
        user += "\n\n" + catalog_context
    data = _chat_json(_PLAN_SYSTEM, user, max_tokens=8192)
    raw_plans = data.get("plans")
    if not isinstance(raw_plans, list):
        raise LLMUnavailable("LLM 返回的方案结构不完整")
    plans = _normalize_plans(raw_plans)
    # 至少要有 2 套结构完整的方案才算成功，否则降级模板
    if len(plans) < 2:
        raise LLMUnavailable(f"LLM 有效方案不足（{len(plans)} 套）")
    return plans


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
            model=settings.vl_model1,
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
