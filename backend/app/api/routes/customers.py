"""客户跟单（店内轻 CRM）：客户记录 + 关联设计任务。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_factory
from app.db.database import get_db
from app.db.models import Customer, DesignTask, User

router = APIRouter()


class CustomerCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    wechat: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None


def _to_dict(c: Customer, task_count: int = 0) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "phone": c.phone,
        "wechat": c.wechat,
        "address": c.address,
        "note": c.note,
        "task_count": task_count,
        "created_at": c.created_at.strftime("%Y-%m-%d") if c.created_at else None,
    }


@router.get("")
def list_customers(
    q: Optional[str] = None,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    stmt = select(Customer).order_by(Customer.id.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Customer.name.like(like) | Customer.phone.like(like))
    customers = db.scalars(stmt).all()
    counts = dict(
        db.execute(
            select(DesignTask.customer_id, func.count(DesignTask.id))
            .where(DesignTask.customer_id.is_not(None))
            .group_by(DesignTask.customer_id)
        ).all()
    )
    return {"customers": [_to_dict(c, counts.get(c.id, 0)) for c in customers]}


@router.post("")
def create_customer(
    data: CustomerCreate,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    customer = Customer(**data.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return _to_dict(customer)


@router.get("/{customer_id}")
def get_customer(
    customer_id: int,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    tasks = db.scalars(
        select(DesignTask)
        .where(DesignTask.customer_id == customer_id)
        .order_by(DesignTask.id.desc())
    ).all()
    return {
        **_to_dict(customer, len(tasks)),
        "tasks": [
            {
                "task_id": t.id,
                "status": t.status,
                "style": t.style,
                "space_type": t.space_type,
                "created_at": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else None,
            }
            for t in tasks
        ],
    }


@router.patch("/{customer_id}")
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(customer, k, v)
    db.commit()
    return _to_dict(customer)


@router.post("/{customer_id}/attach-task")
def attach_task(
    customer_id: int,
    body: dict,
    _user: User = Depends(require_factory),
    db: Session = Depends(get_db),
):
    """把一次设计任务（方案）关联到客户名下。"""
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    task_id = body.get("task_id")
    task = db.get(DesignTask, task_id) if task_id else None
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.customer_id = customer_id
    db.commit()
    return {"status": "ok", "task_id": task.id, "customer_id": customer_id}
