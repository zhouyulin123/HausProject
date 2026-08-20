"""订单池服务：用户发布订单意向，厂家接单报价，用户比价后选择成交。"""

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Order, OrderQuote, User

logger = logging.getLogger(__name__)

ORDER_OPEN = "open"
ORDER_QUOTED = "quoted"
ORDER_ASSIGNED = "assigned"
ORDER_CLOSED = "closed"
ORDER_CANCELLED = "cancelled"

QUOTE_PENDING = "pending"
QUOTE_ACCEPTED = "accepted"
QUOTE_REJECTED = "rejected"


class OrderError(Exception):
    """订单状态/权限相关的可预期错误，路由层转成 4xx。"""


def _gen_order_no() -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    # 使用微秒低几位降低同秒碰撞概率
    micro = datetime.now().microsecond % 10000
    return f"HD{ts}{micro:04d}"


def _display_name(user: Optional[User]) -> Optional[str]:
    """对外展示的用户名；手机号脱敏，保护客户隐私。"""
    if not user:
        return None
    name = user.nickname or user.phone
    if name and len(name) == 11 and name.isdigit():
        return name[:3] + "****" + name[7:]
    return name


def _pending_quote_counts(db: Session, order_ids: list[int]) -> dict[int, int]:
    if not order_ids:
        return {}
    rows = db.execute(
        select(OrderQuote.order_id, func.count(OrderQuote.id))
        .where(
            OrderQuote.order_id.in_(order_ids),
            OrderQuote.status == QUOTE_PENDING,
        )
        .group_by(OrderQuote.order_id)
    ).all()
    return {order_id: count for order_id, count in rows}


def create_order(
    db: Session,
    *,
    customer_id: int,
    source_type: str,
    task_id: Optional[int] = None,
    plan_version_id: Optional[int] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    budget_min: Optional[int] = None,
    budget_max: Optional[int] = None,
) -> Order:
    if source_type == "plan" and not plan_version_id:
        raise OrderError("基于方案的订单必须绑定方案")
    order = Order(
        order_no=_gen_order_no(),
        customer_id=customer_id,
        source_type=source_type,
        task_id=task_id,
        plan_version_id=plan_version_id,
        title=title,
        description=description,
        budget_min=budget_min,
        budget_max=budget_max,
        status=ORDER_OPEN,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _quote_to_dict(quote: OrderQuote, factory: Optional[User]) -> dict[str, Any]:
    return {
        "id": quote.id,
        "order_id": quote.order_id,
        "factory_id": quote.factory_id,
        "factory_name": factory.nickname or factory.phone if factory else None,
        "total_price": quote.total_price,
        "price_min": quote.price_min,
        "price_max": quote.price_max,
        "note": quote.note,
        "status": quote.status,
        "created_at": quote.created_at.strftime("%Y-%m-%d %H:%M") if quote.created_at else None,
    }


def _order_to_dict(order: Order, quotes: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    data = {
        "id": order.id,
        "order_no": order.order_no,
        "customer_id": order.customer_id,
        "source_type": order.source_type,
        "task_id": order.task_id,
        "plan_version_id": order.plan_version_id,
        "title": order.title,
        "description": order.description,
        "budget_min": order.budget_min,
        "budget_max": order.budget_max,
        "status": order.status,
        "assigned_factory_id": order.assigned_factory_id,
        "assigned_quote_id": order.assigned_quote_id,
        "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else None,
    }
    if quotes is not None:
        data["quotes"] = quotes
    return data


def _load_quotes(db: Session, order_id: int) -> list[dict[str, Any]]:
    quotes = db.scalars(
        select(OrderQuote)
        .where(OrderQuote.order_id == order_id)
        .order_by(OrderQuote.id.desc())
    ).all()
    factory_ids = {q.factory_id for q in quotes}
    factories = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_(factory_ids))).all()
    } if factory_ids else {}
    return [_quote_to_dict(q, factories.get(q.factory_id)) for q in quotes]


def list_customer_orders(db: Session, customer_id: int) -> list[dict[str, Any]]:
    orders = db.scalars(
        select(Order).where(Order.customer_id == customer_id).order_by(Order.id.desc())
    ).all()
    counts = _pending_quote_counts(db, [o.id for o in orders])
    result = []
    for o in orders:
        item = _order_to_dict(o)
        item["pending_quote_count"] = counts.get(o.id, 0)
        result.append(item)
    return result


def unread_quote_count(db: Session, customer_id: int) -> int:
    """客户名下所有订单中待选择（pending）的报价总数，用于角标提示。"""
    return (
        db.scalar(
            select(func.count(OrderQuote.id))
            .join(Order, Order.id == OrderQuote.order_id)
            .where(
                Order.customer_id == customer_id,
                OrderQuote.status == QUOTE_PENDING,
            )
        )
        or 0
    )


def list_order_pool(
    db: Session,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    stmt = select(Order).order_by(Order.id.desc())
    if status:
        stmt = stmt.where(Order.status == status)
    orders = db.scalars(stmt).all()
    counts = _pending_quote_counts(db, [o.id for o in orders])
    customer_ids = {o.customer_id for o in orders}
    customers = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_(customer_ids))).all()
    } if customer_ids else {}
    result = []
    for o in orders:
        item = _order_to_dict(o)
        item["customer_name"] = _display_name(customers.get(o.customer_id))
        item["pending_quote_count"] = counts.get(o.id, 0)
        result.append(item)
    return result


def get_order(db: Session, order_id: int) -> Optional[dict[str, Any]]:
    order = db.get(Order, order_id)
    if not order:
        return None
    return _order_to_dict(order, _load_quotes(db, order_id))


def add_quote(
    db: Session,
    *,
    order_id: int,
    factory_id: int,
    total_price: int,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    order = db.get(Order, order_id)
    if not order:
        raise OrderError("订单不存在")
    if order.status not in (ORDER_OPEN, ORDER_QUOTED):
        raise OrderError("订单已结束，无法报价")
    if order.customer_id == factory_id:
        raise OrderError("不能给自己的订单报价")

    existing = db.scalars(
        select(OrderQuote).where(
            OrderQuote.order_id == order_id,
            OrderQuote.factory_id == factory_id,
            OrderQuote.status == QUOTE_PENDING,
        )
    ).first()
    if existing:
        existing.total_price = total_price
        existing.price_min = price_min
        existing.price_max = price_max
        existing.note = note
        quote = existing
    else:
        quote = OrderQuote(
            order_id=order_id,
            factory_id=factory_id,
            total_price=total_price,
            price_min=price_min,
            price_max=price_max,
            note=note,
            status=QUOTE_PENDING,
        )
        db.add(quote)

    if order.status == ORDER_OPEN:
        order.status = ORDER_QUOTED
    db.commit()
    db.refresh(quote)
    factory = db.get(User, factory_id)
    return _quote_to_dict(quote, factory)


def accept_quote(db: Session, *, order_id: int, quote_id: int, customer_id: int) -> dict[str, Any]:
    order = db.get(Order, order_id)
    if not order:
        raise OrderError("订单不存在")
    if order.customer_id != customer_id:
        raise OrderError("只能操作自己的订单")
    if order.status not in (ORDER_OPEN, ORDER_QUOTED):
        raise OrderError("订单已结束")

    quote = db.get(OrderQuote, quote_id)
    if not quote or quote.order_id != order_id or quote.status != QUOTE_PENDING:
        raise OrderError("报价不存在或已失效")

    order.status = ORDER_ASSIGNED
    order.assigned_quote_id = quote.id
    order.assigned_factory_id = quote.factory_id
    quote.status = QUOTE_ACCEPTED
    other_quotes = db.scalars(
        select(OrderQuote).where(
            OrderQuote.order_id == order_id,
            OrderQuote.id != quote.id,
            OrderQuote.status == QUOTE_PENDING,
        )
    ).all()
    for q in other_quotes:
        q.status = QUOTE_REJECTED
    db.commit()
    return _order_to_dict(order, _load_quotes(db, order_id))


def close_order(db: Session, *, order_id: int, actor_id: int, is_admin: bool = False) -> dict[str, Any]:
    order = db.get(Order, order_id)
    if not order:
        raise OrderError("订单不存在")
    if order.customer_id != actor_id and not is_admin:
        raise OrderError("只能关闭自己的订单")
    if order.status in (ORDER_CLOSED, ORDER_CANCELLED):
        raise OrderError("订单已关闭")
    order.status = ORDER_CLOSED
    db.commit()
    return _order_to_dict(order, _load_quotes(db, order_id))
