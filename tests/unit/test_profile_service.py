import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import User
from app.services import llm_service, profile_service


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def _user(db, phone="13800000001"):
    u = User(phone=phone, nickname=phone, role="customer", phone_verified=True)
    db.add(u)
    db.commit()
    return u


@pytest.mark.unit
def test_get_or_create_profile_is_idempotent(db):
    user = _user(db)
    p1 = profile_service.get_or_create_profile(db, user_id=user.id)
    p2 = profile_service.get_or_create_profile(db, user_id=user.id)
    assert p1.id == p2.id


@pytest.mark.unit
def test_merge_profile_updates_budget_and_styles(db):
    user = _user(db)
    profile = profile_service.get_or_create_profile(db, user_id=user.id)

    profile_service.merge_profile(
        profile,
        {"budget_min": 100000, "budget_max": 150000, "preferred_styles": ["奶油风"]},
    )
    assert profile.budget_min == 100000
    assert profile.budget_max == 150000
    assert profile.preferred_styles == ["奶油风"]

    # 再次合并：预算覆盖、风格增量去重
    profile_service.merge_profile(
        profile,
        {"budget_max": 120000, "preferred_styles": ["原木风", "奶油风"]},
    )
    assert profile.budget_max == 120000
    assert profile.preferred_styles == ["原木风", "奶油风"]


@pytest.mark.unit
def test_merge_profile_merges_list_facts_and_overwrites_scalars(db):
    user = _user(db)
    profile = profile_service.get_or_create_profile(db, user_id=user.id)

    profile_service.merge_profile(
        profile,
        {"facts": {"lifestyle": ["在家办公"], "family_structure": "三口之家"}},
    )
    profile_service.merge_profile(
        profile,
        {"facts": {"lifestyle": ["养宠物"], "family_structure": "四口之家"}},
    )
    facts = profile.profile_json
    assert facts["family_structure"] == "四口之家"  # 标量覆盖
    assert facts["lifestyle"] == ["养宠物", "在家办公"]  # 列表合并


@pytest.mark.unit
def test_extract_and_merge_skips_when_llm_unavailable(db, monkeypatch):
    user = _user(db)

    def boom(text):
        raise llm_service.LLMUnavailable("no key")

    monkeypatch.setattr(llm_service, "extract_profile", boom)
    result = profile_service.extract_and_merge(
        db,
        user_id=user.id,
        text="随便说点需求",
    )
    assert result is None


@pytest.mark.unit
def test_build_profile_context_formats_fields(db):
    user = _user(db)
    profile = profile_service.get_or_create_profile(db, user_id=user.id)
    profile.budget_min = 100000
    profile.preferred_styles = ["奶油风"]
    profile.profile_json = {"family_structure": "三口之家"}

    context = profile_service.build_profile_context(profile)
    assert "预算" in context
    assert "奶油风" in context
    assert "三口之家" in context

    assert profile_service.build_profile_context(None) == ""
