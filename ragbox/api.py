"""FastAPI service: multi-tenant document Q&A with citations.

Every document route is authenticated and scoped to the caller's account. There is no shared
index: `IndexStore` hands out one index per account id, so a search physically cannot reach
another tenant's chunks.

Run:  uvicorn ragbox.api:app --reload
      http://127.0.0.1:8000/        demo UI
      http://127.0.0.1:8000/docs    interactive API documentation
"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .answer import answer_extractive, answer_llm
from .demo import DEMO_HTML
from .ingest import SUPPORTED
from .landing import landing_html
from .saas import (Account, FeatureLocked, LimitReached, SaaSError, Tenancy, public_pricing)
from .store import IndexStore

app = FastAPI(title="ragbox", description="Multi-tenant document Q&A with citations (RAG)",
              version="2.0.0")

TENANCY = Tenancy(db_path=os.environ.get("RAGBOX_DB", "ragbox_saas.db"),
                  data_root=os.environ.get("RAGBOX_DATA", "tenant_data"))
STORE = IndexStore()
SESSION_COOKIE = "ragbox_session"


# ------------------------------------------------------------------ auth plumbing
def current_account(ragbox_session: str | None = Cookie(default=None)) -> Account:
    """Resolve the signed-in account, or 401. Every document route depends on this."""
    if not ragbox_session:
        raise HTTPException(401, "sign in first")
    try:
        return TENANCY.account_for_token(ragbox_session)
    except SaaSError as e:
        raise HTTPException(401, str(e))


def _saas_error(e: SaaSError) -> HTTPException:
    """LimitReached / FeatureLocked -> 402 Payment Required; everything else -> 400."""
    if isinstance(e, (LimitReached, FeatureLocked)):
        return HTTPException(402, str(e))
    return HTTPException(400, str(e))


def _tenant_dir(acct: Account) -> Path:
    return TENANCY.tenant_dir(acct.id)


# ------------------------------------------------------------------ models
class Credentials(BaseModel):
    email: str
    password: str


class AskRequest(BaseModel):
    query: str
    k: int = 4
    mode: str = "extractive"          # "extractive" | "llm" (llm is a gated feature)


# ------------------------------------------------------------------ public routes
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def demo() -> str:
    return DEMO_HTML


@app.get("/welcome", response_class=HTMLResponse, include_in_schema=False)
def welcome() -> str:
    """Marketing landing page. Pricing is rendered from PLANS so it can never drift out of
    sync with the limits the product actually enforces."""
    return landing_html()


@app.get("/pricing")
def pricing() -> list[dict]:
    """Plan table for the landing page. Unauthenticated and safe."""
    return public_pricing()


@app.post("/signup")
def signup(creds: Credentials, response: Response) -> dict:
    try:
        acct = TENANCY.signup(creds.email, creds.password)
        token = TENANCY.login(creds.email, creds.password)
    except SaaSError as e:
        raise _saas_error(e)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=30 * 86400)
    return {"email": acct.email, "plan": acct.plan}


@app.post("/login")
def login(creds: Credentials, response: Response) -> dict:
    try:
        token = TENANCY.login(creds.email, creds.password)
    except SaaSError as e:
        raise _saas_error(e)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=30 * 86400)
    acct = TENANCY.account_for_token(token)
    return {"email": acct.email, "plan": acct.entitled_plan}


@app.post("/logout")
def logout(response: Response, ragbox_session: str | None = Cookie(default=None)) -> dict:
    if ragbox_session:
        TENANCY.logout(ragbox_session)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


# ------------------------------------------------------------------ account routes
@app.get("/me")
def me(acct: Account = Depends(current_account)) -> dict:
    return TENANCY.usage_summary(acct)


@app.post("/trial")
def start_trial(acct: Account = Depends(current_account)) -> dict:
    try:
        updated = TENANCY.start_trial(acct.id)
    except SaaSError as e:
        raise _saas_error(e)
    return TENANCY.usage_summary(updated)


# ------------------------------------------------------------------ document routes (scoped)
@app.get("/status")
def status(acct: Account = Depends(current_account)) -> dict:
    ti = STORE.get(acct.id, _tenant_dir(acct))
    return {"plan": acct.entitled_plan, "indexed_chunks": ti.n_chunks,
            "sources": ti.sources, "retrieval_backend": ti.backend,
            "documents": {"used": TENANCY.document_count(acct.id),
                          "limit": acct.limits.max_documents}}


@app.post("/upload")
async def upload(file: UploadFile = File(...), acct: Account = Depends(current_account)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(400, f"unsupported type {suffix}; supported: {sorted(SUPPORTED)}")
    try:
        TENANCY.check_can_upload(acct)                       # plan document cap
        dest = TENANCY.safe_document_path(acct.id, file.filename or "upload")
    except SaaSError as e:
        raise _saas_error(e)

    # stream to a temp file first so we can enforce the size cap before storing anything
    cap_bytes = acct.limits.max_upload_mb * 1024 * 1024
    written = 0
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        while chunk := await file.read(1 << 20):
            written += len(chunk)
            if written > cap_bytes:
                tmp.close()
                os.unlink(tmp.name)
                raise HTTPException(402, f"Files are limited to {acct.limits.max_upload_mb} MB "
                                         f"on the {acct.limits.label} plan.")
            tmp.write(chunk)
        tmp_path = tmp.name
    shutil.move(tmp_path, dest)

    added = STORE.add_document(acct.id, _tenant_dir(acct), dest)      # incremental, not full rebuild
    return {"stored": dest.name, "chunks_added": added,
            "documents": {"used": TENANCY.document_count(acct.id),
                          "limit": acct.limits.max_documents}}


@app.delete("/documents/{filename}")
def delete_document(filename: str, acct: Account = Depends(current_account)) -> dict:
    try:
        path = TENANCY.safe_document_path(acct.id, filename)
    except SaaSError as e:
        raise _saas_error(e)
    if not path.exists():
        raise HTTPException(404, "no such document")
    path.unlink()
    STORE.remove_document(acct.id, _tenant_dir(acct), path.name)
    return {"deleted": path.name}


@app.post("/ask")
def ask(req: AskRequest, acct: Account = Depends(current_account)) -> dict:
    ti = STORE.get(acct.id, _tenant_dir(acct))
    if ti.index is None and ti.n_chunks == 0:
        raise HTTPException(409, "no documents indexed yet - POST a file to /upload first")
    try:
        TENANCY.check_can_ask(acct)                          # monthly question cap
        if req.mode == "llm":
            TENANCY.require_feature(acct, "llm_answers")     # gated feature
    except SaaSError as e:
        raise _saas_error(e)

    hits = ti.search(req.query, k=max(1, min(req.k, 10)))
    ans = answer_llm(req.query, hits) if req.mode == "llm" else answer_extractive(req.query, hits)
    TENANCY.record_question(acct.id)                         # count only successful work
    out = asdict(ans)
    out["usage"] = {"questions_used": TENANCY.questions_used(acct.id),
                    "questions_limit": acct.limits.max_questions_per_month}
    return out
