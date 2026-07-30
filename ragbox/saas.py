"""Multi-tenant SaaS layer: accounts, isolated document stores, and plan limits.

This is what separates a tool from a product. Three guarantees enforced here:

  1. ISOLATION  - every account gets its own document directory and its own index. One tenant
                  can never retrieve a passage from another tenant's documents. This is the
                  single most important property of a document SaaS: a leak is fatal to trust.
  2. LIMITS     - each plan caps documents and monthly questions, checked before work is done.
  3. AUTH       - passwords are stored as salted PBKDF2-SHA256 hashes, never plaintext. Sessions
                  are opaque random tokens, not signed user ids.

Storage is SQLite + a per-tenant folder on disk. Deliberately boring: it runs on a $5 VPS and
can be moved to Postgres/S3 later without changing the interface below.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ------------------------------------------------------------------ plans
@dataclass(frozen=True)
class Plan:
    name: str
    price_usd: int
    max_documents: int
    max_questions_per_month: int
    max_members: int
    api_access: bool


PLANS = {
    "free":     Plan("free", 0, max_documents=10, max_questions_per_month=50,
                     max_members=1, api_access=False),
    "starter":  Plan("starter", 19, max_documents=200, max_questions_per_month=1000,
                     max_members=3, api_access=False),
    "business": Plan("business", 49, max_documents=2000, max_questions_per_month=10 ** 9,
                     max_members=10, api_access=True),
}

SESSION_TTL_SECONDS = 30 * 24 * 3600           # 30 days
PBKDF2_ROUNDS = 260_000                        # deliberately slow: brute-force resistance
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


class SaaSError(Exception):
    """Raised for any user-facing failure (bad login, limit reached, duplicate signup)."""


class LimitReached(SaaSError):
    """A plan limit was hit. Distinct type so the API can answer 402 instead of 400."""


# ------------------------------------------------------------------ password hashing
def hash_password(password: str) -> str:
    """Salted PBKDF2-SHA256. Returned as 'salt$hash' hex - no plaintext ever stored."""
    if len(password) < 8:
        raise SaaSError("password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time comparison, so timing cannot leak how much of the hash matched."""
    try:
        salt_hex, hash_hex = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), PBKDF2_ROUNDS)
    return secrets.compare_digest(dk.hex(), hash_hex)


# ------------------------------------------------------------------ store
SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    plan          TEXT NOT NULL DEFAULT 'free',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    month      TEXT NOT NULL,               -- 'YYYY-MM'
    questions  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, month)
);
CREATE INDEX IF NOT EXISTS idx_sessions_account ON sessions(account_id);
"""


@dataclass
class Account:
    id: int
    email: str
    plan: str

    @property
    def limits(self) -> Plan:
        return PLANS.get(self.plan, PLANS["free"])


class Tenancy:
    """Accounts, sessions, per-tenant storage and plan enforcement."""

    def __init__(self, db_path: str | Path = "ragbox_saas.db",
                 data_root: str | Path = "tenant_data"):
        self.db_path = str(db_path)
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # -------------------------------------------------- accounts
    def signup(self, email: str, password: str, plan: str = "free") -> Account:
        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            raise SaaSError("invalid email address")
        if plan not in PLANS:
            raise SaaSError(f"unknown plan '{plan}'")
        pw = hash_password(password)                       # validates length before any DB write
        with self._conn() as c:
            if c.execute("SELECT 1 FROM accounts WHERE email = ?", (email,)).fetchone():
                raise SaaSError("an account with that email already exists")
            cur = c.execute(
                "INSERT INTO accounts (email, password_hash, plan, created_at) VALUES (?,?,?,?)",
                (email, pw, plan, datetime.now(timezone.utc).isoformat()))
            account_id = int(cur.lastrowid)
        self.tenant_dir(account_id).mkdir(parents=True, exist_ok=True)
        return Account(account_id, email, plan)

    def login(self, email: str, password: str) -> str:
        """Verify credentials and return an opaque session token."""
        email = email.strip().lower()
        with self._conn() as c:
            row = c.execute("SELECT id, password_hash, plan FROM accounts WHERE email = ?",
                            (email,)).fetchone()
        # same error message for unknown email and wrong password: never reveal which
        if row is None or not verify_password(password, row["password_hash"]):
            raise SaaSError("invalid email or password")
        token = secrets.token_urlsafe(32)
        with self._conn() as c:
            c.execute("INSERT INTO sessions (token, account_id, expires_at) VALUES (?,?,?)",
                      (token, row["id"], time.time() + SESSION_TTL_SECONDS))
        return token

    def account_for_token(self, token: str) -> Account:
        with self._conn() as c:
            row = c.execute(
                "SELECT a.id, a.email, a.plan, s.expires_at FROM sessions s "
                "JOIN accounts a ON a.id = s.account_id WHERE s.token = ?", (token,)).fetchone()
            if row is None:
                raise SaaSError("not signed in")
            if row["expires_at"] < time.time():
                c.execute("DELETE FROM sessions WHERE token = ?", (token,))
                raise SaaSError("session expired")
        return Account(row["id"], row["email"], row["plan"])

    def logout(self, token: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def set_plan(self, account_id: int, plan: str) -> None:
        """Called by the billing webhook after a successful payment."""
        if plan not in PLANS:
            raise SaaSError(f"unknown plan '{plan}'")
        with self._conn() as c:
            c.execute("UPDATE accounts SET plan = ? WHERE id = ?", (plan, account_id))

    # -------------------------------------------------- isolated storage
    def tenant_dir(self, account_id: int) -> Path:
        """Per-account document directory. Derived ONLY from the integer id, so a crafted
        email or filename can never escape into another tenant's folder."""
        return self.data_root / f"acct_{int(account_id)}"

    def document_count(self, account_id: int) -> int:
        d = self.tenant_dir(account_id)
        return sum(1 for p in d.glob("*") if p.is_file()) if d.exists() else 0

    def safe_document_path(self, account_id: int, filename: str) -> Path:
        """Resolve an uploaded filename inside the tenant's directory, refusing traversal.

        A client-supplied name like '../../acct_2/secret.pdf' must never resolve outside this
        tenant's folder - that would be a cross-tenant write.
        """
        base = self.tenant_dir(account_id).resolve()
        base.mkdir(parents=True, exist_ok=True)
        name = Path(filename).name                        # strip any directory components
        if not name or name in (".", ".."):
            raise SaaSError("invalid filename")
        target = (base / name).resolve()
        if not str(target).startswith(str(base) + os.sep):
            raise SaaSError("invalid filename")
        return target

    # -------------------------------------------------- limits
    @staticmethod
    def _month() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def questions_used(self, account_id: int) -> int:
        with self._conn() as c:
            row = c.execute("SELECT questions FROM usage WHERE account_id = ? AND month = ?",
                            (account_id, self._month())).fetchone()
        return int(row["questions"]) if row else 0

    def check_can_upload(self, account: Account) -> None:
        if self.document_count(account.id) >= account.limits.max_documents:
            raise LimitReached(
                f"Your {account.plan} plan allows {account.limits.max_documents} documents. "
                f"Upgrade to add more.")

    def check_can_ask(self, account: Account) -> None:
        used = self.questions_used(account.id)
        cap = account.limits.max_questions_per_month
        if used >= cap:
            raise LimitReached(
                f"You've used all {cap} questions on the {account.plan} plan this month. "
                f"Upgrade for more.")

    def record_question(self, account_id: int) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO usage (account_id, month, questions) VALUES (?,?,1) "
                "ON CONFLICT(account_id, month) DO UPDATE SET questions = questions + 1",
                (account_id, self._month()))

    def usage_summary(self, account: Account) -> dict:
        lim = account.limits
        return {
            "email": account.email,
            "plan": account.plan,
            "documents": {"used": self.document_count(account.id), "limit": lim.max_documents},
            "questions": {"used": self.questions_used(account.id),
                          "limit": lim.max_questions_per_month},
            "api_access": lim.api_access,
        }
