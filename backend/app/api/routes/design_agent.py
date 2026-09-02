from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import SessionIdHeader, require_owned_design_task
from app.db.database import get_db
from app.schemas.design_agent import (
    AgentCheckpointResponse,
    AgentTurnRequest,
    AgentTurnResponse,
)
from app.services import design_agent_service


router = APIRouter()


@router.post("/{task_id}/agent-turns", response_model=AgentTurnResponse)
def run_agent_turn(
    task_id: int,
    payload: AgentTurnRequest,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    try:
        return design_agent_service.run_turn(db, task=task, payload=payload)
    except design_agent_service.AgentSceneNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except design_agent_service.AgentSceneVersionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except design_agent_service.AgentIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "message": str(exc)},
        ) from exc
    except design_agent_service.AgentTurnInProgress as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{task_id}/agent-state", response_model=AgentCheckpointResponse)
def get_agent_state(
    task_id: int,
    x_session_id: SessionIdHeader,
    db: Session = Depends(get_db),
):
    task = require_owned_design_task(
        db,
        session_id=x_session_id,
        task_id=task_id,
    )
    return design_agent_service.get_checkpoint(db, task)
