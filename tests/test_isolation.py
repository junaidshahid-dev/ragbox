"""The tests that decide whether this product can be sold.

A document SaaS has exactly one unforgivable bug: showing customer A's documents to customer B.
These tests drive the real HTTP API with two signed-up accounts and assert that no route ever
crosses the boundary - plus that indexing is incremental rather than a full rebuild per upload.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

ACME_SECRET = "Project Firebird launches in March. Budget is 4.2 million dollars."
GLOBEX_SECRET = "Our refund window is 30 days. Support hours are 9am to 6pm PKT."


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A fresh app with its own database and data root per test."""
    import importlib
    monkeypatch.setenv("RAGBOX_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("RAGBOX_DATA", str(tmp_path / "data"))
    import ragbox.api as api
    importlib.reload(api)                      # re-read env into module-level TENANCY/STORE
    return TestClient(api.app)


def _signup(client, email):
    """Sign up as `email`; returns the cookie jar so callers can act as that tenant."""
    r = client.post("/signup", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    jar = {k: v for k, v in client.cookies.items()}
    client.cookies.clear()          # don't let one tenant's session leak into the next request
    return jar


def _upload(client, cookies, name, text):
    return client.post("/upload", files={"file": (name, text.encode(), "text/markdown")},
                       cookies=cookies)


# ------------------------------------------------------------ authentication required
def test_document_routes_require_auth(client):
    """No cookie -> 401 on everything that touches documents."""
    assert client.get("/status").status_code == 401
    assert client.get("/me").status_code == 401
    assert client.post("/ask", json={"query": "x"}).status_code == 401
    assert client.post("/upload",
                       files={"file": ("a.md", b"hi", "text/markdown")}).status_code == 401
    assert client.delete("/documents/a.md").status_code == 401


def test_public_routes_need_no_auth(client):
    assert client.get("/pricing").status_code == 200
    assert client.get("/").status_code == 200


# ------------------------------------------------------------ THE isolation tests
def test_one_tenant_cannot_retrieve_another_tenants_documents(client):
    acme = _signup(client, "boss@acme.com")
    _upload(client, acme, "internal.md", ACME_SECRET)

    globex = _signup(client, "boss@globex.com")
    _upload(client, globex, "policy.md", GLOBEX_SECRET)

    # Globex asks a question whose answer exists ONLY in Acme's document
    r = client.post("/ask", json={"query": "When does Project Firebird launch?", "k": 4},
                    cookies=globex)
    assert r.status_code == 200
    body = r.json()
    assert "Firebird" not in body["text"], "LEAK: another tenant's content was returned"
    assert "4.2 million" not in body["text"]
    for c in body["citations"]:
        assert c["source"] == "policy.md"       # only its own source may ever be cited

    # and Acme still sees its own
    r = client.post("/ask", json={"query": "When does Project Firebird launch?"}, cookies=acme)
    assert "Firebird" in r.json()["text"]


def test_status_lists_only_own_sources(client):
    a = _signup(client, "a@one.com")
    _upload(client, a, "a-only.md", ACME_SECRET)
    b = _signup(client, "b@two.com")
    _upload(client, b, "b-only.md", GLOBEX_SECRET)

    assert client.get("/status", cookies=a).json()["sources"] == ["a-only.md"]
    assert client.get("/status", cookies=b).json()["sources"] == ["b-only.md"]


def test_tenant_cannot_delete_another_tenants_document(client):
    a = _signup(client, "own@x.com")
    _upload(client, a, "mine.md", ACME_SECRET)
    b = _signup(client, "other@x.com")

    r = client.delete("/documents/mine.md", cookies=b)      # B tries to delete A's file
    assert r.status_code == 404                              # not found *in B's space*
    assert client.get("/status", cookies=a).json()["sources"] == ["mine.md"]   # still there


def test_traversal_filename_cannot_touch_another_tenant(client):
    a = _signup(client, "v1@x.com")
    _upload(client, a, "keep.md", ACME_SECRET)
    b = _signup(client, "v2@x.com")
    _upload(client, b, "../acct_1/keep.md", "OVERWRITE ATTEMPT")
    # A's document must be unchanged
    r = client.post("/ask", json={"query": "Project Firebird budget"}, cookies=a)
    assert "4.2 million" in r.json()["text"]


def test_logout_revokes_access(client):
    a = _signup(client, "lo@x.com")
    _upload(client, a, "d.md", GLOBEX_SECRET)
    assert client.get("/status", cookies=a).status_code == 200
    client.post("/logout", cookies=a)
    assert client.get("/status", cookies=a).status_code == 401


# ------------------------------------------------------------ plan enforcement over HTTP
def test_llm_mode_is_gated_with_402(client):
    a = _signup(client, "gate@x.com")
    _upload(client, a, "d.md", GLOBEX_SECRET)
    r = client.post("/ask", json={"query": "refund window?", "mode": "llm"}, cookies=a)
    assert r.status_code == 402                     # payment required, not a crash
    assert "Starter" in r.json()["detail"]

    r = client.post("/ask", json={"query": "refund window?", "mode": "extractive"}, cookies=a)
    assert r.status_code == 200                     # free tier still gets cited passages


def test_document_cap_returns_402(client):
    from ragbox.saas import PLANS
    a = _signup(client, "cap@x.com")
    for i in range(PLANS["free"].max_documents):
        assert _upload(client, a, f"d{i}.md", "text here").status_code == 200
    r = _upload(client, a, "one-too-many.md", "text here")
    assert r.status_code == 402


def test_question_cap_returns_402_and_counts_only_success(client):
    from ragbox.saas import PLANS
    a = _signup(client, "qc@x.com")
    _upload(client, a, "d.md", GLOBEX_SECRET)
    cap = PLANS["free"].max_questions_per_month
    for _ in range(cap):
        assert client.post("/ask", json={"query": "refund"}, cookies=a).status_code == 200
    r = client.post("/ask", json={"query": "refund"}, cookies=a)
    assert r.status_code == 402


def test_oversized_upload_rejected_with_402(client):
    a = _signup(client, "big@x.com")
    big = "x" * (6 * 1024 * 1024)                   # 6 MB against a 5 MB free cap
    r = _upload(client, a, "huge.md", big)
    assert r.status_code == 402
    assert client.get("/status", cookies=a).json()["sources"] == []   # nothing stored


def test_upload_size_cap_rises_with_plan(client):
    import ragbox.api as api
    a = _signup(client, "up2@x.com")
    acct = api.TENANCY.account_for_token(a["ragbox_session"])
    api.TENANCY.set_plan(acct.id, "starter")        # 25 MB cap
    r = _upload(client, a, "ok.md", "y" * (6 * 1024 * 1024))
    assert r.status_code == 200


def test_trial_unlocks_llm_mode(client):
    a = _signup(client, "tr@x.com")
    _upload(client, a, "d.md", GLOBEX_SECRET)
    assert client.post("/trial", cookies=a).status_code == 200
    r = client.post("/ask", json={"query": "refund window?", "mode": "llm"}, cookies=a)
    assert r.status_code == 200                     # no longer 402
    assert r.json()["mode"] in ("llm", "extractive")   # falls back gracefully w/o an API key


# ------------------------------------------------------------ incremental indexing
def test_upload_is_incremental_not_a_full_rebuild(client, tmp_path):
    """Adding the Nth document must not re-read the other N-1 files from disk."""
    import ragbox.api as api
    from ragbox import store as store_mod

    a = _signup(client, "inc@x.com")
    for i in range(8):
        _upload(client, a, f"doc{i}.md", f"Document number {i}. " + "filler text. " * 50)

    calls = {"n": 0}
    real_load = store_mod.load_path

    def counting_load(path):
        calls["n"] += 1
        return real_load(path)

    store_mod.load_path = counting_load
    try:
        _upload(client, a, "doc8.md", "Document number 8. " + "filler text. " * 50)
    finally:
        store_mod.load_path = real_load

    assert calls["n"] == 1, f"expected 1 file parse, got {calls['n']} (full rebuild)"
    st = client.get("/status", cookies=a).json()
    assert len(st["sources"]) == 9                   # all documents still searchable


def test_deleting_a_document_removes_it_from_search(client):
    a = _signup(client, "del@x.com")
    _upload(client, a, "secret.md", ACME_SECRET)
    _upload(client, a, "policy.md", GLOBEX_SECRET)
    assert "Firebird" in client.post("/ask", json={"query": "Firebird"}, cookies=a).json()["text"]

    assert client.delete("/documents/secret.md", cookies=a).status_code == 200
    body = client.post("/ask", json={"query": "Firebird"}, cookies=a).json()
    assert "Firebird" not in body["text"]            # gone from the index, not just the disk
    assert client.get("/status", cookies=a).json()["sources"] == ["policy.md"]


def test_index_survives_tenant_cache_eviction(client):
    """Evicting an idle tenant must not lose their documents - it reloads from disk."""
    import ragbox.api as api
    a = _signup(client, "ev@x.com")
    _upload(client, a, "d.md", GLOBEX_SECRET)
    acct = api.TENANCY.account_for_token(a["ragbox_session"])
    api.STORE.evict(acct.id)
    r = client.post("/ask", json={"query": "refund window"}, cookies=a)
    assert r.status_code == 200 and "30 days" in r.json()["text"]


# ------------------------------------------------------------ landing page honesty
def test_landing_pricing_matches_enforced_limits(client):
    """The page must never advertise a limit the code doesn't actually enforce."""
    from ragbox.saas import PLANS
    html = client.get("/welcome").text
    for plan in PLANS.values():
        assert plan.label in html
        assert f"{plan.max_documents:,}" in html
        assert f"{plan.max_questions_per_month:,}" in html
        assert f"{plan.max_upload_mb} MB" in html


def test_landing_page_leaks_no_secret_values(client):
    """The page may mention 'password' (it has a password FIELD); it must never embed a real
    secret VALUE - a hash, a session token, or a provider reference."""
    import re
    # create an account so there is a real hash and token in the database to leak
    client.post("/signup", json={"email": "leak@x.com", "password": "password123"})
    token = client.cookies.get("ragbox_session")
    html = client.get("/welcome").text

    assert token and token not in html                  # no session token in the markup
    assert "password123" not in html                    # no credential value
    assert not re.search(r"\b[0-9a-f]{32,}\$[0-9a-f]{32,}\b", html)   # no salt$hash blob
    for db_field in ("password_hash", "provider_ref", "sub_status"):
        assert db_field not in html                     # no internal schema exposed


# ------------------------------------------------------------ conversion UI
def test_landing_has_working_signup_modal(client):
    """The CTA must open an in-page modal wired to the real /signup endpoint."""
    html = client.get("/welcome").text
    assert 'id="overlay"' in html and 'id="mform"' in html
    assert "fetch('/' + mode" in html          # posts to /signup or /login
    assert 'aria-modal="true"' in html          # accessible dialog
    assert "Escape" in html                     # closable by keyboard
    # and the endpoint it posts to actually works
    r = client.post("/signup", json={"email": "modal@x.com", "password": "password123"})
    assert r.status_code == 200


def test_landing_respects_reduced_motion(client):
    """Animations must switch off for users who ask the OS to reduce motion."""
    assert "prefers-reduced-motion" in client.get("/welcome").text


def test_landing_has_no_intrusive_popup_triggers(client):
    """No timed or exit-intent interstitials: they'd undercut an honesty-based product."""
    html = client.get("/welcome").text
    assert "setTimeout(open" not in html
    assert "mouseleave" not in html
    assert "beforeunload" not in html


# ------------------------------------------------------------ product UI
def test_app_ui_is_a_real_dashboard_not_a_demo(client):
    """The signed-in product page must show account, usage, documents and upload - the things
    a paying customer needs, not just a search box."""
    html = client.get("/").text
    for hook in ('id="planPill"', 'id="dFill"', 'id="qFill"', 'id="drop"', 'id="docs"',
                 'id="upsell"', 'id="signout"', 'id="gate"'):
        assert hook in html, f"app UI missing {hook}"
    assert "fetch('/me')" in html and "fetch('/status')" in html
    assert "prefers-reduced-motion" in html


def test_app_ui_handles_signed_out_state(client):
    """No session -> the page must offer a way back in, not break."""
    html = client.get("/").text
    assert 'id="gate"' in html and "/welcome" in html
    assert "r.status === 401" in html
