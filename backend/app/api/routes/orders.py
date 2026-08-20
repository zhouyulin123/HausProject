"""订单池接口：普通用户发布订单意向，厂家接单报价，用户比价成交。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_factory
from app.db.database import get_db
from app.db.models import User
from app.services import order_service

router = APIRouter()


class OrderCreate(BaseModel):
    source_type: str = Field(pattern="^(plan|requirement)$")
    task_id: Optional[int] = None
    plan_version_id: Optional[int] = None
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    budget_min: Optional[int] = Field(default=None, ge=0)
    budget_max: Optional[int] = Field(default=None, ge=0)


class QuoteCreate(BaseModel):
    total_price: int = Field(gt=0)
    price_min: Optional[int] = Field(default=None, ge=0)
    price_max: Optional[int] = Field(default=None, ge=0)
    note: Optional[str] = None


class AcceptQuoteRequest(BaseModel):
    quote_id: int


@router.post("")
def create_order(
    data: OrderCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        order = order_service.create_order(
            db,
            customer_id=user.id,
            source_type=data.source_type,
            task_id=data.task_id,
            plan_version_id=data.plan_version_id,
            title=data.title,
            description=data.description,
            budget_min=data.budget_min,
            budget_max=data.budget_max,
        )
    except order_service.OrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"order": order_service._order_to_dict(order)}


@router.get("/mine")
def my_orders(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"orders": order_service.list_customer_orders(db, user.id)}


@router.get("/unread-count")
def unread_quote_count(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"count": order_service.unread_quote_count(db, user.id)}


@router.get("")
def list_order_pool(
    status: Optional[str] = None,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    return {"orders": order_service.list_order_pool(db, status)}


@router.get("/{order_id}")
def get_order(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = order_service.get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    is_factory = user.role in ("factory", "admin")
    if order["customer_id"] != user.id and not is_factory:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {"order": order}


@router.post("/{order_id}/quotes")
def add_quote(
    order_id: int,
    data: QuoteCreate,
    user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    try:
        quote = order_service.add_quote(
            db,
            order_id=order_id,
            factory_id=user.id,
            total_price=data.total_price,
            price_min=data.price_min,
            price_max=data.price_max,
            note=data.note,
        )
    except order_service.OrderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"quote": quote}


@router.post("/{order_id}/accept")
def accept_quote(
    order_id: int,
    req: AcceptQuoteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        order = order_service.accept_quote(
            db,
            order_id=order_id,
            quote_id=req.quote_id,
            customer_id=user.id,
        )
    except order_service.OrderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"order": order}


@router.post("/{order_id}/close")
def close_order(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        order = order_service.close_order(
            db,
            order_id=order_id,
            actor_id=user.id,
            is_admin=user.role == "admin",
        )
    except order_service.OrderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"order": order}
