import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.design_workflow import DesignWorkflow
from app.api.dependencies import (
    SessionIdHeader,
    require_active_session,
    require_owned_design_task,
)
from app.db.database import get_db
from app.db.models import DesignResult, DesignTask, RequirementParseResult, UploadedImage
from app.schemas.tasks import (
    ConfirmRequirementRequest,
    DesignRevisionDetailResponse,
    DesignRevisionListResponse,
    DesignRevisionSummary,
    GenerateResponse,
    RequirementResponse,
    TaskCreate,
    TaskResponse,
    TaskResultResponse,
    TaskStatusResponse,
)
from app.services import (
    anonymous_session_service,
    catalog_service,
    design_version_service,
    llm_service,
    task_service,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_task(db: Session, task_id: int) -> DesignTask:
    task = db.get(DesignTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("", response_model=TaskResponse)
def create_task(
    task_data: TaskCreate,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_active_session(db, x_session_id)
    if task_data.session_id and task_data.session_id != x_session_id:
        raise HTTPException(status_code=400, detail="请求中的会话编号不一致")
    if not anonymous_session_service.session_owns_images(
        db,
        x_session_id,
        task_data.image_ids,
    ):
        raise HTTPException(status_code=403, detail="上传图片不属于当前会话")

    task = DesignTask(raw_user_input=task_data.user_input)
    if task_data.requirement:
        # 前端表单已收集结构化需求，直接进入已确认状态
        task.confirmed_requirement_json = task_data.requirement
        task.status = "confirmed"
        task.progress = 50
        task.space_type = " / ".join(task_data.requirement.get("rooms", [])[:3]) or None
        task.style = " / ".join(task_data.requirement.get("styles", [])[:3]) or None
    else:
        task.status = "analyzing"
        task.progress = 20
    db.add(task)
    db.commit()
    db.refresh(task)
    anonymous_session_service.attach_task(db, x_session_id, task.id)

    # 关联已上传的图片
    if task_data.image_ids:
        for image in db.scalars(
            select(UploadedImage).where(UploadedImage.id.in_(task_data.image_ids))
        ):
            image.task_id = task.id
        db.commit()

    return TaskResponse(task_id=task.id, status=task.status)


@router.get("/{task_id}/requirement", response_model=RequirementResponse)
def get_requirement(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    raw_input = task.raw_user_input or ""

    parser = "llm"
    try:
        parsed = llm_service.parse_requirement(raw_input)
        missing_fields = parsed.pop("missing_fields", [])
        follow_up_questions = parsed.pop("follow_up_questions", [])
    except LLMUnavailable:
        parser = "rule"
        parsed = task_service.parse_requirement(raw_input)
        missing_fields = []
        if parsed["budget"]["max_budget"] == "未指定":
            missing_fields.append("budget")
        if parsed.get("area") is None:
            missing_fields.append("area")
        follow_up_questions = []
        if "area" in missing_fields:
            follow_up_questions.append("您的房间面积大概是多少？")
        if "budget" in missing_fields:
            follow_up_questions.append("您的预算范围大概是多少？")

    db.add(
        RequirementParseResult(
            task_id=task.id,
            raw_input=raw_input,
            parsed_json=parsed,
            missing_fields=missing_fields,
            follow_up_questions=follow_up_questions,
            parser=parser,
        )
    )
    task.status = "waiting_confirm"
    task.progress = 40
    db.commit()

    return RequirementResponse(
        parsed_requirement=parsed,
        missing_fields=missing_fields,
        follow_up_questions=follow_up_questions,
        parser=parser,
    )


@router.post("/{task_id}/confirm-requirement")
def confirm_requirement(
    task_id: int,
    req: ConfirmRequirementRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    task.confirmed_requirement_json = req.confirmed_requirement
    task.status = "confirmed"
    task.progress = 50
    db.commit()
    return {"status": "ok"}


@router.post("/{task_id}/generate", response_model=GenerateResponse)
def generate_design(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    task.status = "generating"
    task.progress = 60
    task.error_message = None
    db.commit()

    try:
        requirement = task.confirmed_requirement_json or task_service.parse_requirement(
            task.raw_user_input or ""
        )

        # 若有上传图片的 VL 分析结果，作为空间上下文一并喂给方案生成
        image_context = []
        for img in db.scalars(
            select(UploadedImage).where(UploadedImage.task_id == task.id)
        ):
            analysis = img.analysis_json or {}
            if analysis.get("findings"):
                image_context.extend(analysis["findings"])
        # 商品库上下文：家具与定制报价只能从自家库里选
        catalog_context = catalog_service.build_catalog_context(db)

        workflow = DesignWorkflow(
            generate_plans=llm_service.generate_plans,
            build_template_plans=task_service.build_template_plans,
            enrich_plans=lambda plans: catalog_service.verify_and_enrich_plans(
                db,
                plans,
            ),
        )
        workflow_result = workflow.run(
            requirement=requirement,
            image_context=image_context,
            catalog_context=catalog_context,
        )
        plans = workflow_result["plans"]
        generator = workflow_result["generator"]
        workflow_trace = workflow_result["node_trace"]
        if generator == "template":
            generation_step = next(
                (
                    step
                    for step in workflow_trace
                    if step.get("node") == "generate_plans"
                ),
                {},
            )
            logger.warning(
                "LLM 方案生成降级到模板: %s",
                generation_step.get("fallback_reason", "未知原因"),
            )

        result = DesignResult(
            task_id=task.id,
            plans_json=plans,
            generator=generator,
            pdf_url=None,
        )
        db.add(result)
        design_version_service.persist_generation(
            db,
            task=task,
            plans=plans,
            generator=generator,
            image_context=image_context,
            workflow_trace=workflow_trace,
        )
        task.status = "completed"
        task.progress = 100
        db.commit()

        return GenerateResponse(
            task_id=task.id,
            status="completed",
            generator=generator,
        )
    except Exception as exc:
        db.rollback()
        failed_task = db.get(DesignTask, task_id)
        if failed_task:
            failed_task.status = "failed"
            failed_task.progress = 0
            failed_task.error_message = str(exc)[:2000]
            db.commit()
        logger.exception("方案生成任务失败: task_id=%s", task_id)
        raise HTTPException(status_code=500, detail="方案生成失败，请稍后重试") from exc


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    return TaskStatusResponse(
        task_id=task.id, status=task.status, progress=task.progress or 0
    )


@router.get("/{task_id}/result", response_model=TaskResultResponse)
def get_task_result(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    revision = design_version_service.get_latest_revision(db, task_id=task_id)
    result = db.scalars(
        select(DesignResult)
        .where(DesignResult.task_id == task_id)
        .order_by(DesignResult.id.desc())
    ).first()
    if not result and not revision:
        raise HTTPException(status_code=404, detail="Result not ready")

    images = [
        {"image_id": img.id, "image_url": img.file_url, "image_type": img.image_type}
        for img in db.scalars(
            select(UploadedImage).where(UploadedImage.task_id == task_id)
        )
    ]
    return TaskResultResponse(
        plans=(
            [plan.plan_json for plan in revision.plans]
            if revision
            else result.plans_json or []
        ),
        generator=revision.generator if revision else result.generator,
        revision_version=revision.version if revision else None,
        images=images,
        pdf_url=result.pdf_url if result else None,
    )


@router.get(
    "/{task_id}/versions",
    response_model=DesignRevisionListResponse,
)
def get_design_versions(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    revisions = design_version_service.list_revisions(db, task_id=task_id)
    summaries = []
    for revision in revisions:
        totals = [
            plan.quote_snapshot.grand_total
            for plan in revision.plans
            if plan.quote_snapshot is not None
        ]
        summaries.append(
            DesignRevisionSummary(
                version=revision.version,
                generator=revision.generator,
                status=revision.status,
                plan_count=len(revision.plans),
                quote_min=min(totals, default=0),
                quote_max=max(totals, default=0),
                created_at=revision.created_at,
            )
        )
    return DesignRevisionListResponse(revisions=summaries)


@router.get(
    "/{task_id}/versions/{version}",
    response_model=DesignRevisionDetailResponse,
)
def get_design_version(
    task_id: int,
    version: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    revision = design_version_service.get_revision(
        db,
        task_id=task_id,
        version=version,
    )
    if not revision:
        raise HTTPException(status_code=404, detail="方案版本不存在")
    return DesignRevisionDetailResponse(
        version=revision.version,
        generator=revision.generator,
        status=revision.status,
        requirement=revision.requirement_snapshot or {},
        image_context=revision.image_context_snapshot or [],
        workflow_trace=revision.workflow_trace_snapshot or [],
        plans=[plan.plan_json for plan in revision.plans],
        created_at=revision.created_at,
    )


@router.post("/{task_id}/export-pdf")
def export_pdf(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    result = db.scalars(
        select(DesignResult)
        .where(DesignResult.task_id == task_id)
        .order_by(DesignResult.id.desc())
    ).first()
    if not result:
        raise HTTPException(status_code=404, detail="Result not ready")
    # mock：真实 PDF 生成留待后续接入
    return {
        "pdf_url": result.pdf_url,
        "artifact_id": result.id,
        "filename": f"design_report_{task_id}.pdf",
    }
