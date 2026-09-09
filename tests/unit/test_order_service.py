import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Order, OrderQuote, User
from app.services import order_service


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def _user(db, phone: str, role: str = "customer") -> User:
    user = User(phone=phone, nickname=phone, role=role, phone_verified=True)
    db.add(user)
    db.commit()
    return user


@pytest.mark.unit
def test_create_requirement_order(db):
    customer = _user(db, "13800000010")
    order = order_service.create_order(
        db,
        customer_id=customer.id,
        source_type="requirement",
        description="全屋定制，奶油风",
        budget_min=30000,
        budget_max=50000,
    )
    assert order.status == "open"
    assert order.order_no.startswith("HD")
    assert order.customer_id == customer.id


@pytest.mark.unit
def test_create_plan_order_requires_plan_version(db):
    customer = _user(db, "13800000011")
    with pytest.raises(order_service.OrderError):
        order_service.create_order(db, customer_id=customer.id, source_type="plan")


@pytest.mark.unit
def test_factory_quote_moves_order_to_quoted(db):
    customer = _user(db, "13800000020")
    factory = _user(db, "13800000021", role="factory")
    order = order_service.create_order(db, customer_id=customer.id, source_type="requirement")

    quote = order_service.add_quote(
        db,
        order_id=order.id,
        factory_id=factory.id,
        total_price=42000,
        note="含全屋柜体与基础五金",
    )
    db.refresh(order)
    assert order.status == "quoted"
    assert quote["total_price"] == 42000
    assert quote["status"] == "pending"


@pytest.mark.unit
def test_factory_cannot_quote_own_order(db):
    factory = _user(db, "13800000030", role="factory")
    order = order_service.create_order(db, customer_id=factory.id, source_type="requirement")
    with pytest.raises(order_service.OrderError):
        order_service.add_quote(
            db,
            order_id=order.id,
            factory_id=factory.id,
            total_price=100,
        )


@pytest.mark.unit
def test_accept_quote_assigns_and_rejects_others(db):
    customer = _user(db, "13800000040")
    f1 = _user(db, "13800000041", role="factory")
    f2 = _user(db, "13800000042", role="factory")
    order = order_service.create_order(db, customer_id=customer.id, source_type="requirement")

    q1 = order_service.add_quote(db, order_id=order.id, factory_id=f1.id, total_price=40000)
    q2 = order_service.add_quote(db, order_id=order.id, factory_id=f2.id, total_price=38000)

    result = order_service.accept_quote(
        db,
        order_id=order.id,
        quote_id=q1["id"],
        customer_id=customer.id,
    )
    assert result["status"] == "assigned"
    assert result["assigned_factory_id"] == f1.id

    db.expire_all()
    quotes = db.scalars(select(OrderQuote).where(OrderQuote.order_id == order.id)).all()
    by_id = {q.id: q.status for q in quotes}
    assert by_id[q1["id"]] == "accepted"
    assert by_id[q2["id"]] == "rejected"


@pytest.mark.unit
def test_accept_quote_rejects_non_owner(db):
    customer = _user(db, "13800000050")
    other = _user(db, "13800000051")
    f1 = _user(db, "13800000052", role="factory")
    order = order_service.create_order(db, customer_id=customer.id, source_type="requirement")
    q1 = order_service.add_quote(db, order_id=order.id, factory_id=f1.id, total_price=100)

    with pytest.raises(order_service.OrderError):
        order_service.accept_quote(
            db,
            order_id=order.id,
            quote_id=q1["id"],
            customer_id=other.id,
        )


@pytest.mark.unit
def test_close_order(db):
    customer = _user(db, "13800000060")
    order = order_service.create_order(db, customer_id=customer.id, source_type="requirement")
    result = order_service.close_order(db, order_id=order.id, actor_id=customer.id)
    assert result["status"] == "closed"
    with pytest.raises(order_service.OrderError):
        order_service.close_order(db, order_id=order.id, actor_id=customer.id)


@pytest.mark.unit
def test_list_customer_orders_returns_pending_quote_count(db):
    customer = _user(db, "13800000070")
    factory = _user(db, "13800000071", role="factory")
    order = order_service.create_order(db, customer_id=customer.id, source_type="requirement")
    order_service.add_quote(db, order_id=order.id, factory_id=factory.id, total_price=100)

    orders = order_service.list_customer_orders(db, customer.id)
    assert len(orders) == 1
    assert orders[0]["pending_quote_count"] == 1


@pytest.mark.unit
def test_list_order_pool_masks_customer_phone(db):
    customer = _user(db, "13800000080")
    order_service.create_order(db, customer_id=customer.id, source_type="requirement")

    orders = order_service.list_order_pool(db)
    assert len(orders) == 1
    assert orders[0]["customer_name"] == "138****0080"


@pytest.mark.unit
def test_unread_quote_count_counts_pending_quotes(db):
    customer = _user(db, "13800000090")
    f1 = _user(db, "13800000091", role="factory")
    f2 = _user(db, "13800000092", role="factory")
    order = order_service.create_order(db, customer_id=customer.id, source_type="requirement")

    assert order_service.unread_quote_count(db, customer.id) == 0

    order_service.add_quote(db, order_id=order.id, factory_id=f1.id, total_price=100)
    order_service.add_quote(db, order_id=order.id, factory_id=f2.id, total_price=200)
    assert order_service.unread_quote_count(db, customer.id) == 2
