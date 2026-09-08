"""影响正式生成输出的规则制品单一契约。"""

from __future__ import annotations


GENERATION_RULE_ARTIFACT_IDS: tuple[str, ...] = (
    "app/agents/design_workflow.py",
    "app/services/catalog_service.py",
    "app/services/custom_furniture_service.py",
    "app/services/furniture_family_rules.py",
    "app/services/furniture_model_rules.py",
    "app/services/generation_provenance.py",
    "app/services/generation_rule_artifacts.py",
    "app/services/generation_scene_service.py",
    "app/services/layout_service.py",
    "app/services/layout_generator.py",
    "app/services/layout_evaluator.py",
    "app/services/layout_repair.py",
    "app/services/product_eligibility.py",
    "app/services/scene_geometry.py",
)
