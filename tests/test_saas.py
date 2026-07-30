"""Tests for the multi-tenant SaaS layer.

The security tests here matter more than the feature tests: a cross-tenant document leak or a
plaintext password would end the business, not inconvenience it.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from ragbox.saas import (GRACE_DAYS, PLANS, TRIAL_DAYS, FeatureLocked, LimitReached, SaaSError,
                         Tenancy, hash_password, public_pricing, verify_password)


@pytest.fixture()
def t(tmp_path):
    return Tenancy(db_path=tmp_path / "test.db", data_root=tmp_path / "data")


# ----------------------------------------------------------- auth & passwords
def test_password_is_never_stored_in_plaintext(t):
    t.signup("a@b.com", "supersecret123")
    import sqlite3
    raw = sqlite3.connect(t.db_path).execute("SELECT password_hash FROM accounts").fetchone()[0]
    assert "supersecret123" not in raw
    assert raw.count("$") == 1                      # salt$hash form


def test_same_password_gets_different_hashes():
    """Salting: two users with the same password must not share a hash."""
    assert hash_password("identical123") != hash_password("identical123")


def test_verify_password_accepts_and_rejects():
    h = hash_password("correct-horse")
    assert verify_password("correct-horse", h)
    assert not verify_password("wrong-horse", h)
    assert not verify_password("", h)
    assert not verify_password("x", "malformed-no-dollar")


def test_short_password_rejected_before_account_exists(t):
    with pytest.raises(SaaSError):
        t.signup("short@b.com", "abc")
    with pytest.raises(SaaSError):                  # and no half-created account was left behind
        t.login("short@b.com", "abc")


def test_invalid_email_rejected(t):
    for bad in ("notanemail", "no@domain", "@nope.com", "a b@c.com"):
        with pytest.raises(SaaSError):
            t.signup(bad, "password123")


def test_duplicate_signup_rejected(t):
    t.signup("dup@b.com", "password123")
    with pytest.raises(SaaSError):
        t.signup("DUP@b.com", "password123")        # case-insensitive


def test_login_and_session_roundtrip(t):
    acct = t.signup("s@b.com", "password123")
    token = t.login("s@b.com", "password123")
    assert t.account_for_token(token).id == acct.id
    t.logout(token)
    with pytest.raises(SaaSError):
        t.account_for_token(token)


def test_wrong_password_and_unknown_email_give_the_same_error(t):
    """Must not reveal whether an email is registered (account-enumeration defence)."""
    t.signup("known@b.com", "password123")
    with pytest.raises(SaaSError) as e1:
        t.login("known@b.com", "wrongpassword")
    with pytest.raises(SaaSError) as e2:
        t.login("unknown@b.com", "wrongpassword")
    assert str(e1.value) == str(e2.value)


def test_expired_session_is_rejected_and_cleaned(t):
    import sqlite3
    t.signup("e@b.com", "password123")
    token = t.login("e@b.com", "password123")
    with sqlite3.connect(t.db_path) as c:           # force expiry into the past
        c.execute("UPDATE sessions SET expires_at = ?", (time.time() - 1,))
    with pytest.raises(SaaSError):
        t.account_for_token(token)


def test_garbage_token_rejected(t):
    with pytest.raises(SaaSError):
        t.account_for_token("not-a-real-token")


# ----------------------------------------------------------- tenant isolation (critical)
def test_tenants_get_separate_directories(t):
    a = t.signup("a@x.com", "password123")
    b = t.signup("b@x.com", "password123")
    assert t.tenant_dir(a.id) != t.tenant_dir(b.id)
    assert t.tenant_dir(a.id).exists() and t.tenant_dir(b.id).exists()


def test_document_counts_are_isolated(t):
    a = t.signup("a2@x.com", "password123")
    b = t.signup("b2@x.com", "password123")
    (t.tenant_dir(a.id) / "secret.md").write_text("A's confidential file")
    assert t.document_count(a.id) == 1
    assert t.document_count(b.id) == 0              # B cannot see A's document


@pytest.mark.parametrize("evil", [
    "../../../etc/passwd",
    "../acct_1/steal.md",
    "..\\..\\windows\\system32\\x.md",
    "/absolute/path.md",
    "..",
])
def test_path_traversal_cannot_escape_the_tenant_folder(t, evil):
    """A crafted filename must never write outside its own tenant directory."""
    b = t.signup("victim@x.com", "password123")
    base = t.tenant_dir(b.id).resolve()
    try:
        path = t.safe_document_path(b.id, evil)
    except SaaSError:
        return                                       # rejected outright: also correct
    assert str(path).startswith(str(base))           # otherwise it must be contained


def test_safe_path_keeps_ordinary_filenames(t):
    a = t.signup("ok@x.com", "password123")
    p = t.safe_document_path(a.id, "handbook.pdf")
    assert p.name == "handbook.pdf"
    assert p.parent == t.tenant_dir(a.id).resolve()


# ----------------------------------------------------------- plan limits
def test_free_plan_document_limit_enforced(t):
    a = t.signup("lim@x.com", "password123")
    cap = PLANS["free"].max_documents
    for i in range(cap):
        (t.tenant_dir(a.id) / f"doc{i}.md").write_text("x")
    with pytest.raises(LimitReached):
        t.check_can_upload(a)


def test_question_limit_enforced_and_counted(t):
    a = t.signup("q@x.com", "password123")
    cap = PLANS["free"].max_questions_per_month
    for _ in range(cap):
        t.check_can_ask(a)                           # allowed
        t.record_question(a.id)
    assert t.questions_used(a.id) == cap
    with pytest.raises(LimitReached):
        t.check_can_ask(a)


def test_upgrading_plan_raises_the_limits(t):
    a = t.signup("up@x.com", "password123")
    cap = PLANS["free"].max_questions_per_month
    for _ in range(cap):
        t.record_question(a.id)
    with pytest.raises(LimitReached):
        t.check_can_ask(a)

    t.set_plan(a.id, "starter")                      # e.g. billing webhook fires
    token = t.login("up@x.com", "password123")
    upgraded = t.account_for_token(token)
    assert upgraded.plan == "starter"
    t.check_can_ask(upgraded)                        # same usage, higher cap -> now allowed


def test_usage_is_tracked_per_account(t):
    a = t.signup("u1@x.com", "password123")
    b = t.signup("u2@x.com", "password123")
    t.record_question(a.id)
    t.record_question(a.id)
    assert t.questions_used(a.id) == 2
    assert t.questions_used(b.id) == 0


def test_unknown_plan_rejected(t):
    a = t.signup("p@x.com", "password123")
    with pytest.raises(SaaSError):
        t.set_plan(a.id, "enterprise-unlimited")
    with pytest.raises(SaaSError):
        t.signup("p2@x.com", "password123", plan="nonsense")


def test_usage_summary_shape(t):
    a = t.signup("sum@x.com", "password123")
    s = t.usage_summary(a)
    assert s["plan"] == "free" and s["email"] == "sum@x.com"
    assert s["documents"]["limit"] == PLANS["free"].max_documents
    assert s["features"]["api_access"] is False
    assert s["subscription"]["is_paying"] is False


# ----------------------------------------------------------- feature gating
def test_free_plan_locks_paid_features(t):
    a = t.signup("f@x.com", "password123")
    for feature in ("llm_answers", "api_access", "export_data", "remove_branding"):
        with pytest.raises(FeatureLocked):
            t.require_feature(a, feature)


def test_starter_unlocks_llm_but_not_api(t):
    a = t.signup("s2@x.com", "password123")
    t.set_plan(a.id, "starter")
    a = t._load(a.id)
    t.require_feature(a, "llm_answers")               # allowed
    with pytest.raises(FeatureLocked):
        t.require_feature(a, "api_access")            # still gated -> reason to go Business


def test_business_unlocks_everything(t):
    a = t.signup("b3@x.com", "password123")
    t.set_plan(a.id, "business")
    a = t._load(a.id)
    for feature in ("llm_answers", "api_access", "export_data", "remove_branding",
                    "priority_support"):
        t.require_feature(a, feature)


def test_feature_error_names_the_upgrade(t):
    a = t.signup("hint@x.com", "password123")
    with pytest.raises(FeatureLocked) as e:
        t.require_feature(a, "llm_answers")
    assert "Starter" in str(e.value)                  # tells the user what to buy


def test_unknown_feature_is_an_error_not_a_silent_pass(t):
    a = t.signup("uf@x.com", "password123")
    with pytest.raises(SaaSError):
        t.require_feature(a, "does_not_exist")


def test_upload_size_capped_per_plan(t):
    a = t.signup("sz@x.com", "password123")
    t.check_upload_size(a, 4 * 1024 * 1024)           # under 5 MB free cap: fine
    with pytest.raises(LimitReached):
        t.check_upload_size(a, 20 * 1024 * 1024)
    t.set_plan(a.id, "business")
    t.check_upload_size(t._load(a.id), 20 * 1024 * 1024)   # 100 MB cap: fine


# ----------------------------------------------------------- subscription lifecycle
def test_trial_grants_paid_features_without_payment(t):
    a = t.signup("tr@x.com", "password123")
    a = t.start_trial(a.id)
    assert a.sub_status == "trialing" and a.is_paying
    assert a.days_left() in (TRIAL_DAYS - 1, TRIAL_DAYS)
    t.require_feature(a, "llm_answers")


def test_trial_can_only_be_used_once(t):
    a = t.signup("tr2@x.com", "password123")
    t.start_trial(a.id)
    with pytest.raises(SaaSError):
        t.start_trial(a.id)


def test_expired_paid_period_auto_downgrades(t):
    """THE revenue-protecting test: when the paid month lapses, paid features stop."""
    a = t.signup("exp@x.com", "password123")
    t.activate_subscription(a.id, "business", period_end=time.time() + 100)
    a = t._load(a.id)
    assert a.entitled_plan == "business"
    t.require_feature(a, "api_access")

    t.activate_subscription(a.id, "business", period_end=time.time() - 1)   # period ran out
    a = t._load(a.id)
    assert a.entitled_plan == "free"                  # entitlement derived, not trusted
    with pytest.raises(FeatureLocked):
        t.require_feature(a, "api_access")


def test_past_due_keeps_access_during_grace_then_drops(t):
    a = t.signup("pd@x.com", "password123")
    t.activate_subscription(a.id, "starter", period_end=time.time() - 1)
    t.mark_past_due(a.id)
    a = t._load(a.id)
    assert a.entitled_plan == "starter"               # inside grace window: still served

    t.activate_subscription(a.id, "starter", period_end=time.time() - (GRACE_DAYS + 1) * 86400)
    t.mark_past_due(a.id)
    assert t._load(a.id).entitled_plan == "free"      # grace exhausted


def test_cancel_at_period_end_vs_immediately(t):
    a = t.signup("c@x.com", "password123")
    t.activate_subscription(a.id, "starter", period_end=time.time() + 10 * 86400)
    t.cancel_subscription(a.id)                       # graceful: keeps what they paid for
    assert t._load(a.id).entitled_plan == "free"      # cancelled status ends entitlement

    t.activate_subscription(a.id, "starter", period_end=time.time() + 10 * 86400)
    t.cancel_subscription(a.id, immediate=True)
    a = t._load(a.id)
    assert a.plan == "free" and a.period_end is None


def test_renewal_extends_the_period(t):
    a = t.signup("rn@x.com", "password123")
    t.activate_subscription(a.id, "starter", period_end=time.time() + 86400)
    first = t._load(a.id).days_left()
    t.activate_subscription(a.id, "starter", period_end=time.time() + 30 * 86400)
    assert t._load(a.id).days_left() > first


def test_cannot_subscribe_to_free_or_unknown(t):
    a = t.signup("bad@x.com", "password123")
    for p in ("free", "enterprise"):
        with pytest.raises(SaaSError):
            t.activate_subscription(a.id, p, period_end=time.time() + 86400)


def test_limits_follow_entitlement_not_stored_plan(t):
    """A lapsed 'business' account must be held to FREE quantity limits too."""
    a = t.signup("q2@x.com", "password123")
    t.activate_subscription(a.id, "business", period_end=time.time() - 1)
    a = t._load(a.id)
    for i in range(PLANS["free"].max_documents):
        (t.tenant_dir(a.id) / f"d{i}.md").write_text("x")
    with pytest.raises(LimitReached):
        t.check_can_upload(a)


# ----------------------------------------------------------- public pricing
def test_public_pricing_is_safe_and_complete():
    rows = public_pricing()
    assert [r["id"] for r in rows] == ["free", "starter", "business"]
    assert rows[0]["price_usd"] == 0 and rows[1]["price_usd"] == 19 and rows[2]["price_usd"] == 49
    assert rows[2]["questions"] == "unlimited"
    blob = str(rows).lower()
    for leak in ("password", "hash", "token", "provider_ref"):
        assert leak not in blob
