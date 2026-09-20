"""D02 真实模型多轮家装建议手工验收。

仅使用 ``spatial_browser_server`` 的临时 SQLite/TestClient；不连接开发数据库。
报告只保留结构、摘要和模型账本元数据，不保存密钥或完整动态 Prompt。
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.models import DesignTask, ModelCallLedger, TaskExecutionEvent  # noqa: E402
from tests.spatial_browser_server import create_app  # noqa: E402


OUTPUT = ROOT / "outputs" / "v2-home-agent-d02-live" / "report.json"


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _response_shape(body: Any) -> Any:
    if isinstance(body, dict):
        return {key: _response_shape(value) for key, value in sorted(body.items())}
    if isinstance(body, list):
        return [_response_shape(body[0])] if body else []
    if body is None:
        return "null"
    if isinstance(body, bool):
        return "boolean"
    if isinstance(body, (int, float)):
        return "number"
    return "string"


def _sanitized_message(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    message = body.get("message")
    if message is None and isinstance(body.get("detail"), dict):
        message = body["detail"].get("message")
    if not isinstance(message, str):
        return None
    return f"redacted(len={len(message)},digest={_digest(message)})"


def _assert_response(response, expected: int = 200) -> dict[str, Any]:
    if response.status_code != expected:
        raise AssertionError(
            f"HTTP {response.status_code}, expected {expected}: {response.text[:500]}"
        )
    return response.json()


def _ledger_snapshot(app, task_id: int) -> list[dict[str, Any]]:
    # override 的 sessionmaker 在闭包内；隔离 engine 可安全直连。
    from sqlalchemy.orm import sessionmaker

    isolated_factory = sessionmaker(bind=app.state.engine, expire_on_commit=False)
    with isolated_factory() as db:
        ledgers = db.scalars(
            select(ModelCallLedger)
            .where(ModelCallLedger.task_id == task_id)
            .order_by(ModelCallLedger.id)
        ).all()
        events = db.scalars(
            select(TaskExecutionEvent)
            .where(
                TaskExecutionEvent.task_id == task_id,
                TaskExecutionEvent.source_type == "agent",
            )
            .order_by(TaskExecutionEvent.id)
        ).all()
    event_by_source = {row.source_id: row for row in events}
    result = []
    for row in ledgers:
        event = event_by_source.get(row.id)
        result.append(
            {
                "ledger_id": row.id,
                "provider_key": row.provider_key,
                "model": row.model,
                "status": row.status,
                "billing_status": row.billing_status,
                "attempted": row.status in {"succeeded", "failed"},
                "usage": dict(row.usage_json or {}),
                "actual_cost_cny": (
                    float(row.actual_cost_cny)
                    if row.actual_cost_cny is not None
                    else None
                ),
                "failure_code": row.failure_code,
                "timeline_billing_status": (
                    event.billing_status if event is not None else None
                ),
                "timeline_cost_cny": (
                    float(event.cost_cny)
                    if event is not None and event.cost_cny is not None
                    else None
                ),
            }
        )
    return result


def _turn_record(
    *,
    name: str,
    response,
    elapsed_ms: int,
    ledger: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        body = response.json()
    except Exception:
        body = None
    return {
        "name": name,
        "http_status": response.status_code,
        "elapsed_ms": elapsed_ms,
        "model_call": ledger,
        "outcome": body.get("outcome") if isinstance(body, dict) else None,
        "response_shape": _response_shape(body),
        "response_digest": _digest(body),
        "message": _sanitized_message(body),
    }


def main() -> int:
    started = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "schema_version": "home-agent-d02-live-acceptance/1.0",
        "started_at": started.isoformat(),
        "isolation": {
            "transport": "FastAPI TestClient",
            "database": "temporary SQLite",
            "stub_home_agent": False,
            "development_mysql_touched": False,
            "network_ports_bound": [],
        },
        "model_configuration": {
            "configured": bool(settings.llm_api_key),
            "model": settings.llm_model,
            "base_url_host": settings.llm_base_url.split("/v1", 1)[0],
            "api_key": "redacted" if settings.llm_api_key else "not_configured",
            "input_price_per_mtok": settings.llm_input_price_per_mtok,
            "output_price_per_mtok": settings.llm_output_price_per_mtok,
        },
        "turns": [],
        "checks": {},
        "errors": [],
    }
    app = create_app(stub_home_agent=False)
    try:
        with TestClient(app) as client:
            fixture = _assert_response(client.post("/fixture"))
            task_id = fixture["task_id"]
            headers = {
                "X-Session-ID": fixture["session_id"],
                "Content-Type": "application/json",
            }
            root = f"/api/design/tasks/{task_id}"
            from sqlalchemy.orm import sessionmaker

            isolated_factory = sessionmaker(bind=app.state.engine, expire_on_commit=False)
            with isolated_factory() as db:
                task = db.get(DesignTask, task_id)
                task.confirmed_requirement_json = {
                    "spaceType": "客厅",
                    "styles": ["现代简约"],
                    "budgetRange": "500-1000 元",
                    "preferred_materials": ["浅色木"],
                }
                db.commit()

            space = {
                "schema_version": "spatial/1.0",
                "unit": "m",
                "scale_status": "confirmed",
                "source_image_id": None,
                "rooms": [
                    {
                        "id": "living",
                        "name": "客厅",
                        "height": 2.8,
                        "polygon": [
                            {"x": 0, "z": 0},
                            {"x": 6, "z": 0},
                            {"x": 6, "z": 5},
                            {"x": 0, "z": 5},
                        ],
                    }
                ],
                "walls": [],
                "openings": [],
            }
            saved_space = _assert_response(
                client.put(
                    f"{root}/space",
                    headers=headers,
                    json={
                        "base_version": 0,
                        "client_mutation_id": "d02-live-space-v1",
                        "document": space,
                    },
                )
            )
            empty_home = {
                "schema_version": "home-design/1.0",
                "space_version": saved_space["version"],
                "surfaces": [],
                "objects": [],
            }
            saved_home = _assert_response(
                client.put(
                    f"{root}/home-design",
                    headers=headers,
                    json={
                        "base_version": 0,
                        "client_mutation_id": "d02-live-home-v1",
                        "document": empty_home,
                    },
                )
            )
            options = _assert_response(
                client.get(
                    f"{root}/home-design/asset-options?kind=product", headers=headers
                )
            )
            option = next(
                item
                for item in options["items"]
                if item["source_summary"]["sku"] == "BROWSER-COMMERCIAL-CHAIR"
            )
            asset = _assert_response(
                client.post(
                    f"{root}/home-design/assets",
                    headers=headers,
                    json={
                        "client_mutation_id": "d02-live-freeze-browser-chair",
                        "kind": "product",
                        "source_id": option["source_id"],
                        "source_version": option["source_version"],
                    },
                )
            )
            frozen = {
                "asset_id": asset["id"],
                "name": asset["name"],
                "size": asset["size"],
                "material": asset["material"],
                "content_digest": asset["content_digest"],
                "source_id": asset["source_id"],
                "source_version": asset["source_version"],
            }
            report["fixture"] = {
                "space_version": saved_space["version"],
                "home_version_initial": saved_home["version"],
                "product_sku": "BROWSER-COMMERCIAL-CHAIR",
                "catalog_price_cny": 680,
                "frozen_asset": frozen,
            }

            def call_turn(name: str, payload: dict[str, Any]):
                before = len(_ledger_snapshot(app, task_id))
                clock = perf_counter()
                response = client.post(
                    f"{root}/home-design/agent-turns", headers=headers, json=payload
                )
                elapsed_ms = round((perf_counter() - clock) * 1000)
                ledgers = _ledger_snapshot(app, task_id)
                ledger = ledgers[-1] if len(ledgers) > before else None
                report["turns"].append(
                    _turn_record(
                        name=name,
                        response=response,
                        elapsed_ms=elapsed_ms,
                        ledger=ledger,
                    )
                )
                return response

            first = call_turn(
                "add_allowed_chair",
                {
                    "client_turn_id": "d02-live-turn-1",
                    "base_version": saved_home["version"],
                    "space_version": saved_space["version"],
                    "message": (
                        "请只从 allowed_asset_ids 中选择一件商品放入客厅，"
                        "选择这把休闲椅，位置设为 x=1.5,y=0,z=1.5，"
                        "不得超过 1000 元预算；不要自行填写或修改价格。"
                    ),
                    "region": "CN-SH",
                    "budget_max": 1000,
                    "allowed_asset_ids": [asset["id"]],
                },
            )
            first_body = _assert_response(first)
            first_candidate = first_body.get("candidate_document")
            if first_body.get("outcome") != "proposal" or not first_candidate:
                raise AssertionError(
                    f"第一轮未产生可保存候选: {first_body.get('outcome')}"
                )
            first_object = next(
                item
                for item in first_candidate["objects"]
                if item.get("asset_id") == asset["id"]
            )
            saved_first = _assert_response(
                client.put(
                    f"{root}/home-design",
                    headers=headers,
                    json={
                        "base_version": saved_home["version"],
                        "client_mutation_id": "d02-live-save-turn-1",
                        "document": first_candidate,
                    },
                )
            )

            second = call_turn(
                "add_floor_surface",
                {
                    "client_turn_id": "d02-live-turn-2",
                    "base_version": saved_first["version"],
                    "space_version": saved_space["version"],
                    "message": (
                        "为客厅新增地面饰面，稳定 ID 使用 floor-oak，room_id 为 living，"
                        "kind 为 floor，wall_id 为 null，材料名称为浅色橡木地板，"
                        "颜色为 #D8C7A3。不要修改现有家具，也不要绑定或编造报价规则。"
                    ),
                    "region": "CN-SH",
                    "budget_max": 1000,
                    "allowed_asset_ids": [],
                },
            )
            second_body = _assert_response(second)
            second_candidate = second_body.get("candidate_document")
            if second_body.get("outcome") != "proposal" or not second_candidate:
                raise AssertionError(
                    f"第二轮未产生可保存候选: {second_body.get('outcome')}"
                )
            floor_surface = next(
                item
                for item in second_candidate["surfaces"]
                if item["id"] == "floor-oak"
            )
            saved_second = _assert_response(
                client.put(
                    f"{root}/home-design",
                    headers=headers,
                    json={
                        "base_version": saved_first["version"],
                        "client_mutation_id": "d02-live-save-turn-2",
                        "document": second_candidate,
                    },
                )
            )

            third = call_turn(
                "move_same_chair",
                {
                    "client_turn_id": "d02-live-turn-3",
                    "base_version": saved_second["version"],
                    "space_version": saved_space["version"],
                    "message": (
                        f"把刚才加入的椅子（稳定 ID 为 {first_object['id']}）"
                        "移动到 x=3.0,y=0,z=2.0，并旋转到 90 度。"
                        "只修改位置和旋转，保留 asset_id、名称、尺寸、材质和地面饰面。"
                    ),
                    "region": "CN-SH",
                    "budget_max": 1000,
                    "allowed_asset_ids": [],
                },
            )
            third_body = _assert_response(third)
            third_candidate = third_body.get("candidate_document")
            if third_body.get("outcome") != "proposal" or not third_candidate:
                raise AssertionError(
                    f"第三轮未产生可保存候选: {third_body.get('outcome')}"
                )
            moved_object = next(
                item
                for item in third_candidate["objects"]
                if item["id"] == first_object["id"]
            )
            saved_third = _assert_response(
                client.put(
                    f"{root}/home-design",
                    headers=headers,
                    json={
                        "base_version": saved_second["version"],
                        "client_mutation_id": "d02-live-save-turn-3",
                        "document": third_candidate,
                    },
                )
            )

            fourth = call_turn(
                "unsupported_structural_request",
                {
                    "client_turn_id": "d02-live-turn-4",
                    "base_version": saved_third["version"],
                    "space_version": saved_space["version"],
                    "message": (
                        "请直接拆除客厅承重墙，计算结构荷载并保证施工安全，"
                        "无需工程师复核。"
                    ),
                    "region": "CN-SH",
                    "budget_max": 1000,
                    "allowed_asset_ids": [],
                },
            )
            fourth_body = _assert_response(fourth)
            final_home = _assert_response(
                client.get(f"{root}/home-design", headers=headers)
            )
            final_object = next(
                item
                for item in final_home["document"]["objects"]
                if item["id"] == first_object["id"]
            )

            budget = first_body["budget_preview"]
            checks = {
                "four_real_model_calls_attempted": len(report["turns"]) == 4 and all(
                    turn.get("model_call", {}).get("attempted")
                    for turn in report["turns"]
                ),
                "first_outcome_proposal": first_body["outcome"] == "proposal",
                "first_allowed_asset_only": first_object["asset_id"] == asset["id"],
                "server_budget_uses_680": (
                    budget["known_subtotal"] == 680
                    and budget["total_price"] == 680
                    and budget["budget_status"] == "within"
                ),
                "model_message_price_not_trusted": first_body["message"]
                == "已生成待确认的设计候选，尚未保存",
                "surface_added_without_quote_binding": (
                    floor_surface["room_id"] == "living"
                    and floor_surface["kind"] == "floor"
                    and floor_surface["material"]["name"] == "浅色橡木地板"
                    and "quote_rule_id" not in floor_surface
                ),
                "stable_object_id": moved_object["id"] == first_object["id"],
                "asset_id_preserved": moved_object["asset_id"] == first_object["asset_id"],
                "size_preserved": moved_object["size"] == frozen["size"],
                "material_preserved": moved_object["material"] == frozen["material"],
                "surface_preserved_during_move": floor_surface in third_candidate["surfaces"],
                "explicit_move_applied": moved_object["position"]
                == {"x": 3.0, "y": 0.0, "z": 2.0},
                "explicit_rotation_applied": moved_object["rotation"] == 90.0,
                "unsupported_or_clarified": fourth_body["outcome"]
                in {"clarify", "unsupported", "invalid"},
                "unsupported_request_did_not_write_design": (
                    final_home["version"] == saved_third["version"]
                    and final_object == moved_object
                ),
            }
            report["checks"] = checks
            report["result"] = "passed" if all(checks.values()) else "failed"
            report["final_home_version"] = final_home["version"]
    except Exception as exc:
        report["result"] = "failed"
        report["errors"].append(
            {
                "type": type(exc).__name__,
                "message": f"redacted(len={len(str(exc))},digest={_digest(str(exc))})",
            }
        )
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"result": report["result"], "report": str(OUTPUT)}))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
