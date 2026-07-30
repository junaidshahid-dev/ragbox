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
    """A monthly subscription tier.

    Two kinds of gating, deliberately:
      QUANTITY  - how much you can do (documents, questions, members)
      FEATURES  - what you can do at all (LLM answers, API, export, branding)

    Quantity limits alone are weak product design: a heavy free user costs you money while a
    light paying user feels cheated. Feature gates are what make an upgrade obviously worth it.
    """
    name: str
    label: str
    price_usd: int                    # per MONTH - recurring, not one-off
    max_documents: int
    max_questions_per_month: int
    # ---- feature gates ----
    llm_answers: bool                 # AI-written answers vs raw cited passages
    priority_support: bool
    max_upload_mb: int                # per-file size ceiling


# v1 ships ONLY what the engine can actually deliver today. Deliberately omitted until built:
# team members, API keys, data export, white-labelling. Promising an unbuilt feature is how a
# first customer becomes a refund.
#
# Question caps are FINITE on every tier, including the top one. Each AI answer costs real API
# money (~$0.007), so an "unlimited" $49 plan is a standing invitation to lose money on a heavy
# user. A hard ceiling keeps every tier gross-margin positive.
PLANS = {
    "free": Plan(
        "free", "Free", 0,
        max_documents=10, max_questions_per_month=50,
        llm_answers=False,            # cited passages only - proves value, withholds the polish
        priority_support=False, max_upload_mb=5),
    "starter": Plan(
        "starter", "Starter", 19,
        max_documents=200, max_questions_per_month=1000,
        llm_answers=True,             # the main reason to upgrade
        priority_support=False, max_upload_mb=25),
    "business": Plan(
        "business", "Business", 49,
        max_documents=1000, max_questions_per_month=5000,
        llm_answers=True, priority_support=True, max_upload_mb=50),
}

TRIAL_DAYS = 14                       # paid features, no card - converts far better than a demo
GRACE_DAYS = 3                        # keep access briefly after a failed renewal, then downgrade

SESSION_TTL_SECONDS = 30 * 24 * 3600           # 30 days
PBKDF2_ROUNDS = 260_000                        # deliberately slow: brute-force resistance
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


class SaaSError(Exception):
    """Raised for any user-facing failure (bad login, limit reached, duplicate signup)."""


class LimitReached(SaaSError):
    """A quantity limit was hit. Distinct type so the API can answer 402 instead of 400."""


class FeatureLocked(SaaSError):
    """The plan does not include this feature at all. Also a 402 (payment required)."""


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
    created_at    TEXT NOT NULL,
    -- subscription lifecycle: this is what makes revenue RECURRING
    sub_status    TEXT NOT NULL DEFAULT 'none',   -- none|trialing|active|past_due|cancelled
    period_end    REAL,                           -- unix ts when the paid month expires
    provider_ref  TEXT                            -- MoR subscription id (Dodo/Lemon Squeezy)
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
    sub_status: str = "none"
    period_end: float | None = None

    @property
    def entitled_plan(self) -> str:
        """The plan the account is ACTUALLY entitled to right now.

        A paid plan whose billing period has lapsed (beyond the grace window) silently falls
        back to free. Entitlement is derived from subscription state on every request rather
        than trusted from the stored plan column - so a lapsed customer cannot keep paid
        features just because nobody ran a cron job.
        """
        if self.plan == "free":
            return "free"
        if self.sub_status in ("active", "trialing"):
            if self.period_end is None or time.time() <= self.period_end:
                return self.plan
            return "free"                                  # period ended
        if self.sub_status == "past_due":
            # inside the grace window the customer keeps access; after it, downgrade
            if self.period_end is not None and time.time() <= self.period_end + GRACE_DAYS * 86400:
                return self.plan
            return "free"
        return "free"                                      # cancelled / none

    @property
    def limits(self) -> Plan:
        return PLANS.get(self.entitled_plan, PLANS["free"])

    @property
    def is_paying(self) -> bool:
        return self.entitled_plan != "free"

    def days_left(self) -> int | None:
        if self.period_end is None or not self.is_paying:
            return None
        return max(0, int((self.period_end - time.time()) // 86400))


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
                "SELECT a.id, a.email, a.plan, a.sub_status, a.period_end, s.expires_at "
                "FROM sessions s JOIN accounts a ON a.id = s.account_id "
                "WHERE s.token = ?", (token,)).fetchone()
            if row is None:
                raise SaaSError("not signed in")
            if row["expires_at"] < time.time():
                c.execute("DELETE FROM sessions WHERE token = ?", (token,))
                raise SaaSError("session expired")
        return Account(row["id"], row["email"], row["plan"], row["sub_status"], row["period_end"])

    def logout(self, token: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def account_count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])

    def _load(self, account_id: int) -> Account:
        with self._conn() as c:
            r = c.execute("SELECT id, email, plan, sub_status, period_end FROM accounts "
                          "WHERE id = ?", (account_id,)).fetchone()
        if r is None:
            raise SaaSError("no such account")
        return Account(r["id"], r["email"], r["plan"], r["sub_status"], r["period_end"])

    # -------------------------------------------------- subscription lifecycle
    def start_trial(self, account_id: int, plan: str = "starter") -> Account:
        """Give paid features for TRIAL_DAYS with no card. Only once per account."""
        if plan not in PLANS or plan == "free":
            raise SaaSError(f"cannot trial plan '{plan}'")
        acct = self._load(account_id)
        if acct.sub_status != "none":
            raise SaaSError("this account has already used its trial")
        end = time.time() + TRIAL_DAYS * 86400
        with self._conn() as c:
            c.execute("UPDATE accounts SET plan=?, sub_status='trialing', period_end=? "
                      "WHERE id=?", (plan, end, account_id))
        return self._load(account_id)

    def activate_subscription(self, account_id: int, plan: str, period_end: float,
                              provider_ref: str | None = None) -> Account:
        """Called by the billing webhook on a successful payment or renewal.

        `period_end` is when the paid month runs out - the provider sends a fresh one on each
        renewal, so a lapsed webhook naturally causes a downgrade rather than free service.
        """
        if plan not in PLANS or plan == "free":
            raise SaaSError(f"cannot subscribe to plan '{plan}'")
        with self._conn() as c:
            c.execute("UPDATE accounts SET plan=?, sub_status='active', period_end=?, "
                      "provider_ref=COALESCE(?, provider_ref) WHERE id=?",
                      (plan, float(period_end), provider_ref, account_id))
        return self._load(account_id)

    def mark_past_due(self, account_id: int) -> Account:
        """Payment failed. Access continues through the grace window, then auto-downgrades."""
        with self._conn() as c:
            c.execute("UPDATE accounts SET sub_status='past_due' WHERE id=?", (account_id,))
        return self._load(account_id)

    def cancel_subscription(self, account_id: int, immediate: bool = False) -> Account:
        """Cancel. By default the customer keeps what they paid for until period_end."""
        with self._conn() as c:
            if immediate:
                c.execute("UPDATE accounts SET plan='free', sub_status='cancelled', "
                          "period_end=NULL WHERE id=?", (account_id,))
            else:
                c.execute("UPDATE accounts SET sub_status='cancelled' WHERE id=?", (account_id,))
        return self._load(account_id)

    def set_plan(self, account_id: int, plan: str) -> None:
        """Direct plan change (admin/manual). Paid plans get a one-month period."""
        if plan not in PLANS:
            raise SaaSError(f"unknown plan '{plan}'")
        with self._conn() as c:
            if plan == "free":
                c.execute("UPDATE accounts SET plan='free', sub_status='none', period_end=NULL "
                          "WHERE id=?", (account_id,))
            else:
                c.execute("UPDATE accounts SET plan=?, sub_status='active', period_end=? "
                          "WHERE id=?", (plan, time.time() + 30 * 86400, account_id))

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

    def require_feature(self, account: Account, feature: str) -> None:
        """Gate a FEATURE (not a quantity). Raises FeatureLocked with an upgrade hint.

            tenancy.require_feature(acct, "llm_answers")
        """
        lim = account.limits
        if not hasattr(lim, feature):
            raise SaaSError(f"unknown feature '{feature}'")
        if not getattr(lim, feature):
            nicer = next((p.label for p in PLANS.values()
                          if getattr(p, feature) and p.price_usd > lim.price_usd), "a paid plan")
            raise FeatureLocked(
                f"'{feature.replace('_', ' ')}' is not included in the {lim.label} plan. "
                f"Available on {nicer}.")

    def check_upload_size(self, account: Account, size_bytes: int) -> None:
        cap = account.limits.max_upload_mb
        if size_bytes > cap * 1024 * 1024:
            raise LimitReached(f"Files are limited to {cap} MB on the {account.limits.label} plan.")

    def usage_summary(self, account: Account) -> dict:
        lim = account.limits
        return {
            "email": account.email,
            "plan": account.entitled_plan,
            "plan_label": lim.label,
            "price_usd_per_month": lim.price_usd,
            "subscription": {"status": account.sub_status, "days_left": account.days_left(),
                             "is_paying": account.is_paying},
            "documents": {"used": self.document_count(account.id), "limit": lim.max_documents},
            "questions": {"used": self.questions_used(account.id),
                          "limit": lim.max_questions_per_month},
            "features": {"llm_answers": lim.llm_answers,
                         "priority_support": lim.priority_support,
                         "max_upload_mb": lim.max_upload_mb},
        }


def public_pricing() -> list[dict]:
    """Plan table for the landing page - no secrets, safe to serve unauthenticated."""
    return [{
        "id": p.name, "label": p.label, "price_usd": p.price_usd,
        "documents": p.max_documents, "questions": p.max_questions_per_month,
        "upload_mb": p.max_upload_mb, "llm_answers": p.llm_answers,
        "priority_support": p.priority_support,
    } for p in PLANS.values()]
