"""Accounts for the hosted relay: sign in with Google or Apple, then one token per device.

A self-hosted relay has no accounts: each library is opened by its own secret
(relay/storage.py). The hosted one adds this module, switched on by `DATABASE_URL`:
a person signs in with Google or Apple, the account gets a relay library of its own,
and every device they link gets its own relay token, which can be cancelled alone.

What an account never holds is a key. Signing in proves who someone is; the library
stays encrypted under a key that only reaches a new device from the Mac's QR code or
the recovery kit (AGENTS.md, "Encryption and keys"), so this server, and whoever runs
it, can open nothing.

The sign-in checks follow Dequeue's (`~/dequeue/backend/app/auth.py`), which learned
them the hard way:
- an id token is VERIFIED (the provider's signature, issuer, expiry, and that it was
  issued to one of our own clients), never just decoded: a decoded-only token is one
  anyone can write by hand, naming anyone;
- the Mac's Google sign-in hands the one-time code to the server, which holds the
  "Desktop app" client's secret, so no secret ships inside the app;
- Apple issues tokens to whichever client asked: the Services ID (web flow) or the
  bundle id (a native sheet). Both are ours;
- refresh tokens are rows, so a sign-out ends them, and a swapped one keeps working for
  a short grace in case the reply carrying its successor was lost.

One place this is stricter than Dequeue: Apple's web flow posts back to the relay, which
must hand the result to the Mac. Dequeue sent the browser to whatever address the
request named, with the tokens in it. Here the address must be this Mac's own engine
(loopback, one path), and what it carries is a one-time code good for two minutes,
which the engine swaps for the session itself (`/auth/handoff`).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column,
    Float,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    and_,
    create_engine,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)

log = logging.getLogger("enqueue.accounts")

DEVICE_TOKEN_PREFIX = "enqd_"
_DEFAULT_JWT_SECRET = "dev-jwt-secret-change-me"


# ---- settings ----------------------------------------------------------------------


@dataclass
class AccountSettings:
    database_url: str
    jwt_secret: str = _DEFAULT_JWT_SECRET
    environment: str = "development"
    access_ttl_s: int = 15 * 60
    refresh_ttl_s: int = 60 * 24 * 3600
    refresh_grace_s: int = 5 * 60
    # Google: the Web client (what Android and the web flow get tokens for) and the
    # "Desktop app" client the Mac uses, whose secret stays here.
    google_client_id: str | None = None
    google_desktop_client_id: str | None = None
    google_desktop_client_secret: str | None = None
    google_jwks_url: str = "https://www.googleapis.com/oauth2/v3/certs"
    google_token_url: str = "https://oauth2.googleapis.com/token"
    # Apple: the Services ID (web flow) and the app's bundle id (a native sheet).
    apple_client_id: str | None = None
    apple_bundle_id: str = "com.sudohnim.enqueue"
    apple_jwks_url: str = "https://appleid.apple.com/auth/keys"
    rate_limit_per_min: int = 30
    # Enqueue's own OpenRouter key, for the included assistant (relay/ai.py); without
    # it the assistant answers 503 and everything else works.
    openrouter_api_key: str | None = None
    openrouter_url: str = "https://openrouter.ai/api/v1"
    # The Authorization value set on RevenueCat's webhook, which it sends back; the
    # webhook refuses everything while it is unset.
    revenuecat_webhook_auth: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> AccountSettings | None:
        """Accounts are on when DATABASE_URL is set; a self-hosted relay has none."""
        url = os.getenv("DATABASE_URL", "").strip()
        if not url:
            return None
        return cls(
            database_url=url,
            jwt_secret=os.getenv("JWT_SECRET", _DEFAULT_JWT_SECRET),
            environment=os.getenv("ENVIRONMENT", "production"),
            google_client_id=os.getenv("GOOGLE_CLIENT_ID") or None,
            google_desktop_client_id=os.getenv("GOOGLE_DESKTOP_CLIENT_ID") or None,
            google_desktop_client_secret=os.getenv("GOOGLE_DESKTOP_CLIENT_SECRET") or None,
            apple_client_id=os.getenv("APPLE_CLIENT_ID") or None,
            apple_bundle_id=os.getenv("APPLE_BUNDLE_ID", "com.sudohnim.enqueue"),
            revenuecat_webhook_auth=os.getenv("REVENUECAT_WEBHOOK_AUTH") or None,
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
        )

    def check(self) -> None:
        """Production refuses to start on a secret anyone could guess: a token signed
        with it would be a sign-in as anyone."""
        if self.environment == "production" and (
            self.jwt_secret == _DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32
        ):
            raise RuntimeError("JWT_SECRET must be set to 32+ random characters in production")


def _engine_url(url: str) -> str:
    # Railway hands out postgres:// or postgresql://; SQLAlchemy needs the driver named.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


# ---- tables ------------------------------------------------------------------------

metadata = MetaData()

accounts_t = Table(
    "accounts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("provider", String(16), nullable=False),  # google | apple
    Column("subject", String(255), nullable=False),  # the provider's stable user id
    Column("email", String(320)),
    Column("display_name", String(255)),
    Column("picture", String(1024)),  # the provider's picture address (Google only)
    Column("tier", String(16), nullable=False, default="free"),  # mirrors pro_until
    # Pro until this time (RevenueCat's expiry, or a grant); none or past is free.
    Column("pro_until", Float),
    # When the RevenueCat event behind pro_until happened: an older one arriving late
    # never undoes a newer one.
    Column("pro_event_at", Float),
    Column("library_id", String(64)),  # the relay library (relay/storage.py), once made
    Column("created_at", Float, nullable=False),
    UniqueConstraint("provider", "subject", name="uq_accounts_provider_subject"),
)

refresh_tokens_t = Table(
    "refresh_tokens",
    metadata,
    Column("jti", String(64), primary_key=True),
    Column("account_id", String(36), nullable=False, index=True),
    Column("family", String(64), nullable=False, index=True),
    Column("expires_at", Float, nullable=False),
    Column("rotated_at", Float),
    Column("revoked_at", Float),
)

devices_t = Table(
    "devices",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("account_id", String(36), nullable=False, index=True),
    Column("name", String(100), nullable=False),
    Column("kind", String(16)),  # computer | phone: what the plan's limits count
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_at", Float, nullable=False),
    Column("last_seen_at", Float),
    Column("revoked_at", Float),
)

# What the included assistant (relay/ai.py) cost each account each calendar month (UTC),
# in US dollars as OpenRouter reported it. Counts only: never a prompt or an answer.
ai_usage_t = Table(
    "ai_usage",
    metadata,
    Column("account_id", String(36), primary_key=True),
    Column("month", String(7), primary_key=True),  # YYYY-MM
    Column("cost_usd", Float, nullable=False, default=0.0),
    Column("requests", Float, nullable=False, default=0.0),
    Column("tokens", Float, nullable=False, default=0.0),
)

# A sign-in finished in a browser, waiting for the Mac to collect it: one use, two
# minutes. Only the code's hash is kept, and the session is issued on collection.
handoffs_t = Table(
    "handoffs",
    metadata,
    Column("code_hash", String(64), primary_key=True),
    Column("account_id", String(36), nullable=False),
    Column("expires_at", Float, nullable=False),
)

HANDOFF_TTL_S = 120

# What each plan holds (AGENTS.md, "The paid tier"). Free is one computer and one phone;
# Pro raises the counts and the storage. A phone over the limit is replaced (the one
# used least recently stops opening the library once the new one first syncs); a
# computer over it is refused, since silently cutting off another Mac would lose work.
GiB = 1024**3
PLANS = {
    "free": {"computers": 1, "phones": 1, "storage_bytes": 1 * GiB},
    "pro": {"computers": 5, "phones": 5, "storage_bytes": 50 * GiB},
}
DEVICE_KINDS = ("computer", "phone")
PRO_ENTITLEMENT = "pro"
# A purchase with no expiry (a lifetime product, a grant "for good").
FOREVER = 4102444800.0  # 2100-01-01


def tier_of(account: dict, now: float | None = None) -> str:
    until = account.get("pro_until")
    return "pro" if until and until > (now or time.time()) else "free"


# A device token nobody has used this long after it was made was never linked: a
# phone's code shown and not scanned, a computer's code not typed in. It stops opening
# anything and leaves the account's list, so showing a code twice leaves no clutter.
UNUSED_DEVICE_TTL_S = 30 * 60

# Where Apple's web flow may send the browser back to: the Mac's own engine, nothing
# else. An open address here would hand a sign-in to any site that asked for one.
_RETURN_TO = re.compile(r"http://127\.0\.0\.1:\d{2,5}/account/apple/done")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---- the service -------------------------------------------------------------------


class Accounts:
    """Accounts, sessions and device tokens over one SQL database."""

    def __init__(self, settings: AccountSettings, storage) -> None:
        settings.check()
        self.s = settings
        self.storage = storage  # relay/storage.py RelayStorage: makes the libraries
        self.engine = create_engine(_engine_url(settings.database_url), future=True)
        # The tables are created at start, not migrated: this database holds only these
        # few. A column added later is added here too (_add_missing_columns); past a
        # handful of those, this database gets an Alembic history of its own.
        metadata.create_all(self.engine)
        self._add_missing_columns()
        self._device_cache: dict[str, tuple[float, str | None]] = {}
        self._cache_lock = threading.Lock()
        self._ai_lock = threading.Lock()
        self._jwks: dict[str, Any] = {}

    def _add_missing_columns(self) -> None:
        """create_all makes missing tables, never missing columns: add the ones this
        version brought to a table an older one made (one ALTER each, once)."""
        from sqlalchemy import inspect, text

        wanted = {
            "accounts": {
                "picture": "VARCHAR(1024)",
                "pro_until": "FLOAT",
                "pro_event_at": "FLOAT",
            },
            "devices": {"kind": "VARCHAR(16)"},
        }
        for table, columns in wanted.items():
            have = {c["name"] for c in inspect(self.engine).get_columns(table)}
            for name, sql_type in columns.items():
                if name in have:
                    continue
                with self.engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
                    if (table, name) == ("devices", "kind"):
                        # Before kinds, a phone was the device the Mac named "Phone".
                        conn.execute(
                            text(
                                "UPDATE devices SET kind = CASE WHEN name = 'Phone'"
                                " THEN 'phone' ELSE 'computer' END"
                            )
                        )

    # -- id tokens -------------------------------------------------------------------

    def _signing_key(self, token: str, jwks_url: str):
        import jwt

        client = self._jwks.get(jwks_url)
        if client is None:
            client = self._jwks[jwks_url] = jwt.PyJWKClient(jwks_url)
        return client.get_signing_key_from_jwt(token).key

    def _verify(self, token: str, *, jwks_url: str, audiences: list[str], issuers: list[str]):
        import jwt

        if not audiences:
            # Nothing to check the audience against: a token issued to any app at all
            # would pass. Refuse, so a service missing its client ids fails closed.
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "sign in not configured")
        try:
            return jwt.decode(
                token,
                self._signing_key(token, jwks_url),
                algorithms=["RS256"],
                audience=audiences,
                issuer=issuers,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
        except jwt.PyJWKClientError as exc:
            log.error("signing keys could not be fetched: %s", exc)
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "sign in unavailable") from exc
        except jwt.InvalidTokenError as exc:
            log.warning("id token refused: %s", exc)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in token invalid") from exc

    def verify_google(self, id_token: str) -> dict:
        audiences = [c for c in (self.s.google_client_id, self.s.google_desktop_client_id) if c]
        return self._verify(
            id_token,
            jwks_url=self.s.google_jwks_url,
            audiences=audiences,
            issuers=["https://accounts.google.com", "accounts.google.com"],
        )

    def verify_apple(self, identity_token: str) -> dict:
        audiences = [c for c in (self.s.apple_client_id, self.s.apple_bundle_id) if c]
        if not self.s.apple_client_id:
            audiences = []  # no Services ID set up yet: Apple sign-in is not configured
        return self._verify(
            identity_token,
            jwks_url=self.s.apple_jwks_url,
            audiences=audiences,
            issuers=["https://appleid.apple.com"],
        )

    def google_desktop_code(self, code: str, code_verifier: str, redirect_uri: str) -> str:
        """Swap the Mac's one-time code for an id token, with the secret kept here."""
        if not (self.s.google_desktop_client_id and self.s.google_desktop_client_secret):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "sign in not configured")
        resp = httpx.post(
            self.s.google_token_url,
            data={
                "code": code,
                "client_id": self.s.google_desktop_client_id,
                "client_secret": self.s.google_desktop_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            timeout=15,
        )
        id_token = resp.json().get("id_token") if resp.status_code == 200 else None
        if not id_token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "google sign in failed")
        return id_token

    # -- accounts ----------------------------------------------------------------------

    def account_for(self, provider: str, claims: dict, display_name: str | None = None) -> dict:
        """The account for a verified sign-in, made the first time."""
        subject = str(claims.get("sub") or "")
        if not subject:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in token has no subject")
        email = claims.get("email")
        name = display_name or claims.get("name") or email
        picture = (
            claims.get("picture")
            if str(claims.get("picture") or "").startswith("https://")
            else None
        )
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    select(accounts_t).where(
                        and_(accounts_t.c.provider == provider, accounts_t.c.subject == subject)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                account_id = str(uuid.uuid4())
                conn.execute(
                    insert(accounts_t).values(
                        id=account_id,
                        provider=provider,
                        subject=subject,
                        email=email,
                        display_name=name,
                        picture=picture,
                        tier="free",
                        created_at=time.time(),
                    )
                )
            else:
                account_id = row["id"]
                # Apple sends the email only on the first sign-in: never blank it.
                changes = {}
                if email and email != row["email"]:
                    changes["email"] = email
                if display_name and display_name != row["display_name"]:
                    changes["display_name"] = display_name
                if picture and picture != row["picture"]:
                    changes["picture"] = picture
                if changes:
                    conn.execute(
                        update(accounts_t).where(accounts_t.c.id == account_id).values(**changes)
                    )
            return dict(
                conn.execute(select(accounts_t).where(accounts_t.c.id == account_id))
                .mappings()
                .one()
            )

    def get_account(self, account_id: str) -> dict | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(select(accounts_t).where(accounts_t.c.id == account_id))
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def ensure_library(self, account: dict) -> str:
        """The account's relay library, made the first time a device is linked."""
        if account.get("library_id"):
            return account["library_id"]
        lid = self.storage.add_account_library(
            label=f"account {account['id'][:8]}",
            quota_bytes=PLANS[tier_of(account)]["storage_bytes"],
        )
        with self.engine.begin() as conn:
            conn.execute(
                update(accounts_t)
                .where(and_(accounts_t.c.id == account["id"], accounts_t.c.library_id.is_(None)))
                .values(library_id=lid)
            )
            # Two devices linking at once: the first one's library wins.
            return conn.execute(
                select(accounts_t.c.library_id).where(accounts_t.c.id == account["id"])
            ).scalar_one()

    def delete_account(self, account_id: str) -> None:
        """End every session and device, refuse the library and delete what it holds."""
        account = self.get_account(account_id)
        if account is None:
            return
        with self.engine.begin() as conn:
            conn.execute(
                delete(refresh_tokens_t).where(refresh_tokens_t.c.account_id == account_id)
            )
            conn.execute(delete(devices_t).where(devices_t.c.account_id == account_id))
            conn.execute(delete(handoffs_t).where(handoffs_t.c.account_id == account_id))
            conn.execute(delete(ai_usage_t).where(ai_usage_t.c.account_id == account_id))
            conn.execute(delete(accounts_t).where(accounts_t.c.id == account_id))
        if account.get("library_id"):
            self.storage.revoke_library(account["library_id"])
        self._forget_devices()

    # -- sessions --------------------------------------------------------------------

    def _sign(self, payload: dict) -> str:
        import jwt

        return jwt.encode(payload, self.s.jwt_secret, algorithm="HS256")

    def _decode(self, token: str, *, verify_exp: bool = True) -> dict:
        import jwt

        try:
            return jwt.decode(
                token,
                self.s.jwt_secret,
                algorithms=["HS256"],
                options={"verify_exp": verify_exp},
            )
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc

    def issue_pair(self, account: dict, family: str | None = None) -> dict:
        now = time.time()
        access = self._sign(
            {
                "sub": account["id"],
                "typ": "access",
                "iat": int(now),
                "exp": int(now + self.s.access_ttl_s),
            }
        )
        jti = uuid.uuid4().hex
        family = family or uuid.uuid4().hex
        with self.engine.begin() as conn:
            conn.execute(
                insert(refresh_tokens_t).values(
                    jti=jti,
                    account_id=account["id"],
                    family=family,
                    expires_at=now + self.s.refresh_ttl_s,
                )
            )
        refresh = self._sign(
            {
                "sub": account["id"],
                "typ": "refresh",
                "jti": jti,
                "iat": int(now),
                "exp": int(now + self.s.refresh_ttl_s),
            }
        )
        return {
            "access_token": access,
            "refresh_token": refresh,
            "account": _public(account),
        }

    def refresh(self, token: str) -> dict:
        claims = self._decode(token)
        if claims.get("typ") != "refresh":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not a refresh token")
        now = time.time()
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    select(refresh_tokens_t).where(refresh_tokens_t.c.jti == str(claims.get("jti")))
                )
                .mappings()
                .first()
            )
            if row is None or row["revoked_at"] or row["account_id"] != claims.get("sub"):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session ended")
            if row["rotated_at"] is None:
                conn.execute(
                    update(refresh_tokens_t)
                    .where(refresh_tokens_t.c.jti == row["jti"])
                    .values(rotated_at=now)
                )
            elif now - row["rotated_at"] > self.s.refresh_grace_s:
                # Swapped for a newer one long enough ago that this is no lost reply.
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session ended")
        account = self.get_account(row["account_id"])
        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session ended")
        return self.issue_pair(account, family=row["family"])

    def logout(self, token: str) -> None:
        """End the sign-in a refresh token belongs to. Never raises: there is simply
        nothing left to end for an expired, malformed or unknown token."""
        try:
            claims = self._decode(token, verify_exp=False)
        except HTTPException:
            return
        with self.engine.begin() as conn:
            row = conn.execute(
                select(refresh_tokens_t.c.family).where(
                    refresh_tokens_t.c.jti == str(claims.get("jti"))
                )
            ).first()
            if row is not None:
                conn.execute(
                    update(refresh_tokens_t)
                    .where(
                        and_(
                            refresh_tokens_t.c.family == row[0],
                            refresh_tokens_t.c.revoked_at.is_(None),
                        )
                    )
                    .values(revoked_at=time.time())
                )

    def logout_all(self, account_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(refresh_tokens_t)
                .where(
                    and_(
                        refresh_tokens_t.c.account_id == account_id,
                        refresh_tokens_t.c.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=time.time())
            )

    def account_from_access(self, token: str) -> dict:
        claims = self._decode(token)
        if claims.get("typ") != "access":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not an access token")
        account = self.get_account(str(claims.get("sub")))
        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no such account")
        return account

    # -- handoffs --------------------------------------------------------------------

    def start_handoff(self, account: dict) -> str:
        code = secrets.token_urlsafe(32)
        now = time.time()
        with self.engine.begin() as conn:
            conn.execute(delete(handoffs_t).where(handoffs_t.c.expires_at < now))
            conn.execute(
                insert(handoffs_t).values(
                    code_hash=_hash(code), account_id=account["id"], expires_at=now + HANDOFF_TTL_S
                )
            )
        return code

    def redeem_handoff(self, code: str) -> dict:
        """The session for a one-time code, which is gone once used."""
        with self.engine.begin() as conn:
            row = (
                conn.execute(select(handoffs_t).where(handoffs_t.c.code_hash == _hash(code)))
                .mappings()
                .first()
            )
            if row is not None:
                conn.execute(delete(handoffs_t).where(handoffs_t.c.code_hash == row["code_hash"]))
        if row is None or row["expires_at"] < time.time():
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in expired, try again")
        account = self.get_account(row["account_id"])
        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no such account")
        return self.issue_pair(account)

    # -- devices ---------------------------------------------------------------------

    def _live_devices(self, conn, account_id: str, kind: str, now: float) -> list:
        """The account's devices of a kind that count against its plan: not cancelled,
        and used, or made recently enough that their code may still be scanned. Least
        recently used first."""
        return conn.execute(
            select(devices_t.c.id)
            .where(
                and_(
                    devices_t.c.account_id == account_id,
                    func.coalesce(devices_t.c.kind, "computer") == kind,
                    devices_t.c.revoked_at.is_(None),
                    or_(
                        devices_t.c.last_seen_at.is_not(None),
                        devices_t.c.created_at >= now - UNUSED_DEVICE_TTL_S,
                    ),
                )
            )
            .order_by(func.coalesce(devices_t.c.last_seen_at, devices_t.c.created_at))
        ).all()

    def add_device(self, account: dict, name: str, kind: str = "computer") -> dict:
        """A relay token for one device. Shown once: only its hash is kept.

        A computer past the plan's count is refused (402). A phone never is: the
        newest replaces the least recently used once it first syncs (library_for_device),
        so a code shown and never scanned cuts nobody off."""
        kind = kind if kind in DEVICE_KINDS else "computer"
        library = self.ensure_library(account)
        now = time.time()
        if kind == "computer":
            limit = PLANS[tier_of(account, now)]["computers"]
            with self.engine.connect() as conn:
                live = self._live_devices(conn, account["id"], "computer", now)
            if len(live) >= limit:
                raise HTTPException(
                    status.HTTP_402_PAYMENT_REQUIRED,
                    (
                        "Enqueue sync's free plan covers one computer. Remove the other one"
                        " under Devices, or go Pro on your phone."
                        if tier_of(account, now) == "free"
                        else f"Enqueue sync covers {limit} computers. Remove one under Devices."
                    ),
                )
        token = DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)
        device_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                insert(devices_t).values(
                    id=device_id,
                    account_id=account["id"],
                    name=(name or "device")[:100],
                    kind=kind,
                    token_hash=_hash(token),
                    created_at=now,
                )
            )
        return {"device_id": device_id, "relay_token": token, "library_id": library}

    def devices(self, account_id: str) -> list[dict]:
        """The account's devices, without the codes that were never used (they are
        deleted here, once past UNUSED_DEVICE_TTL_S)."""
        cutoff = time.time() - UNUSED_DEVICE_TTL_S
        with self.engine.begin() as conn:
            conn.execute(
                delete(devices_t).where(
                    and_(
                        devices_t.c.account_id == account_id,
                        devices_t.c.last_seen_at.is_(None),
                        devices_t.c.created_at < cutoff,
                    )
                )
            )
            return [
                {
                    k: r[k]
                    for k in ("id", "name", "kind", "created_at", "last_seen_at", "revoked_at")
                }
                for r in conn.execute(
                    select(devices_t)
                    .where(devices_t.c.account_id == account_id)
                    .order_by(devices_t.c.created_at)
                ).mappings()
            ]

    def rename_device(self, account_id: str, device_id: str, name: str) -> bool:
        with self.engine.begin() as conn:
            return (
                conn.execute(
                    update(devices_t)
                    .where(and_(devices_t.c.id == device_id, devices_t.c.account_id == account_id))
                    .values(name=(name or "device")[:100])
                ).rowcount
                > 0
            )

    def revoke_device(self, account_id: str, device_id: str) -> bool:
        with self.engine.begin() as conn:
            done = (
                conn.execute(
                    update(devices_t)
                    .where(
                        and_(
                            devices_t.c.id == device_id,
                            devices_t.c.account_id == account_id,
                            devices_t.c.revoked_at.is_(None),
                        )
                    )
                    .values(revoked_at=time.time())
                ).rowcount
                > 0
            )
        self._forget_devices()
        return done

    def library_for_device(self, token: str) -> str | None:
        """The library a device token opens, or None (unknown, cancelled, or the
        account is gone). Remembered for a few seconds: the relay asks on every
        request, and a phone pulls every few seconds."""
        if not token.startswith(DEVICE_TOKEN_PREFIX):
            return None
        key = _hash(token)
        now = time.time()
        with self._cache_lock:
            hit = self._device_cache.get(key)
            if hit and now - hit[0] < 15:
                return hit[1]
        replaced = False
        with self.engine.begin() as conn:
            row = conn.execute(
                select(
                    devices_t.c.id,
                    devices_t.c.last_seen_at,
                    accounts_t.c.library_id,
                    devices_t.c.created_at,
                    devices_t.c.kind,
                    devices_t.c.account_id,
                    accounts_t.c.pro_until,
                )
                .select_from(devices_t.join(accounts_t, accounts_t.c.id == devices_t.c.account_id))
                .where(and_(devices_t.c.token_hash == key, devices_t.c.revoked_at.is_(None)))
            ).first()
            if row is not None and row[1] is None and now - row[3] > UNUSED_DEVICE_TTL_S:
                row = None  # never used in time: the code was not scanned
            if row is not None and row[1] is None and row[4] == "phone":
                replaced = self._replace_phones(conn, row[5], row[0], row[6], now)
            if row is not None and (row[1] is None or now - row[1] > 300):
                conn.execute(
                    update(devices_t).where(devices_t.c.id == row[0]).values(last_seen_at=now)
                )
        if replaced:
            self._forget_devices()
        library = row[2] if row is not None else None
        # Only a token that opens something is remembered: caching refusals let anyone
        # grow this map without end by sending made-up tokens. Old entries go when it
        # is large.
        with self._cache_lock:
            if len(self._device_cache) > 4096:
                for old in [k for k, v in self._device_cache.items() if now - v[0] > 15]:
                    del self._device_cache[old]
            if library is not None:
                self._device_cache[key] = (now, library)
            else:
                self._device_cache.pop(key, None)
        return library

    def _replace_phones(self, conn, account_id: str, new_id: str, pro_until, now: float) -> bool:
        """A phone's first sync: the phones past the plan's count, least recently used
        first, stop opening the library (on free, linking a new phone moves sync to it)."""
        limit = PLANS[tier_of({"pro_until": pro_until}, now)]["phones"]
        others = [
            r[0] for r in self._live_devices(conn, account_id, "phone", now) if r[0] != new_id
        ]
        gone = others[: max(0, len(others) - (limit - 1))]
        if gone:
            conn.execute(update(devices_t).where(devices_t.c.id.in_(gone)).values(revoked_at=now))
        return bool(gone)

    def account_for_device(self, token: str) -> dict | None:
        """The account a live device token belongs to (the phone asking for its plan)."""
        if not token.startswith(DEVICE_TOKEN_PREFIX) or self.library_for_device(token) is None:
            return None
        with self.engine.connect() as conn:
            account_id = conn.execute(
                select(devices_t.c.account_id).where(devices_t.c.token_hash == _hash(token))
            ).scalar()
        return self.get_account(account_id) if account_id else None

    # -- plans -----------------------------------------------------------------------

    def plan(self, account: dict) -> dict:
        tier = tier_of(account)
        lib = account.get("library_id")
        return {
            "account_id": account["id"],
            "tier": tier,
            "pro_until": account.get("pro_until") if tier == "pro" else None,
            "limits": PLANS[tier],
            "used_bytes": self.storage.used_bytes(lib) if lib else 0,
            "ai": self.ai_month(account["id"], tier),
        }

    # -- the included assistant's meter (relay/ai.py) -----------------------------------

    def ai_month(self, account_id: str, tier: str | None = None) -> dict:
        """This calendar month's included-AI spend against the plan's cap."""
        from .. import included_ai

        if tier is None:
            account = self.get_account(account_id)
            tier = tier_of(account) if account else "free"
        month = time.strftime("%Y-%m", time.gmtime())
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(ai_usage_t).where(
                        and_(ai_usage_t.c.account_id == account_id, ai_usage_t.c.month == month)
                    )
                )
                .mappings()
                .first()
            )
        return {
            "month": month,
            "used_usd": round(float(row["cost_usd"]) if row else 0.0, 4),
            "cap_usd": included_ai.MONTHLY_CAP_USD[tier],
            "requests": int(row["requests"]) if row else 0,
        }

    def ai_record(self, account_id: str, cost_usd: float, tokens: int) -> None:
        month = time.strftime("%Y-%m", time.gmtime())
        with self._ai_lock, self.engine.begin() as conn:
            done = conn.execute(
                update(ai_usage_t)
                .where(and_(ai_usage_t.c.account_id == account_id, ai_usage_t.c.month == month))
                .values(
                    cost_usd=ai_usage_t.c.cost_usd + cost_usd,
                    requests=ai_usage_t.c.requests + 1,
                    tokens=ai_usage_t.c.tokens + tokens,
                )
            ).rowcount
            if not done:
                conn.execute(
                    insert(ai_usage_t).values(
                        account_id=account_id,
                        month=month,
                        cost_usd=cost_usd,
                        requests=1,
                        tokens=tokens,
                    )
                )

    def set_pro_until(self, account_id: str, until: float | None, event_at: float | None = None):
        """Pro until a time (None: free from now), and the library's storage to match.
        Nothing stored is removed when it shrinks; new writes are refused past it."""
        account = self.get_account(account_id)
        if account is None:
            return
        tier = tier_of({"pro_until": until})
        values = {"pro_until": until, "tier": tier}
        if event_at is not None:
            values["pro_event_at"] = event_at
        with self.engine.begin() as conn:
            conn.execute(update(accounts_t).where(accounts_t.c.id == account_id).values(**values))
        if account.get("library_id"):
            self.storage.set_quota(account["library_id"], PLANS[tier]["storage_bytes"])
        self._forget_devices()

    def accounts_by_email(self, email: str) -> list[dict]:
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(accounts_t).where(func.lower(accounts_t.c.email) == email.lower())
                ).mappings()
            ]

    def _rc_account(self, app_user_id) -> dict | None:
        # The phone configures RevenueCat with the account id, so an id that is not one
        # (an anonymous "$RCAnonymousID:...") names nobody here.
        try:
            uuid.UUID(str(app_user_id))
        except (ValueError, TypeError):
            return None
        return self.get_account(str(app_user_id))

    def revenuecat(self, body: dict) -> dict:
        """Apply one RevenueCat webhook event.

        Pro lasts until the event's expiry, whatever the event is called: a
        cancellation keeps Pro to the end of the period paid for, a refund or an
        expiration ends it (RevenueCat sends a refund as a cancellation whose expiry is
        now), a billing problem keeps it through the grace period. Only events about the
        `pro` entitlement count, and an event older than the last one applied is
        ignored, since RevenueCat may deliver out of order."""
        event = body.get("event") or {}
        kind = str(event.get("type") or "")
        if kind == "TRANSFER":
            return self._rc_transfer(event)
        entitlements = set(event.get("entitlement_ids") or [])
        if event.get("entitlement_id"):
            entitlements.add(event["entitlement_id"])
        if PRO_ENTITLEMENT not in entitlements:
            return {"ok": True, "ignored": kind or "event"}
        ids = [event.get("app_user_id"), event.get("original_app_user_id")]
        ids += list(event.get("aliases") or [])
        account = next((a for a in map(self._rc_account, ids) if a), None)
        if account is None:
            log.info("revenuecat %s for no account here", kind)
            return {"ok": True, "ignored": "unknown user"}
        at = (event.get("event_timestamp_ms") or time.time() * 1000) / 1000
        if account.get("pro_event_at") and at < account["pro_event_at"]:
            return {"ok": True, "ignored": "older event"}
        expires = event.get("expiration_at_ms")
        if kind == "EXPIRATION":
            until = None
        elif expires is None:
            until = FOREVER
        else:
            until = float(expires) / 1000
        self.set_pro_until(account["id"], until, event_at=at)
        log.info(
            "revenuecat %s: account %s is %s",
            kind,
            account["id"][:8],
            tier_of({"pro_until": until}),
        )
        return {"ok": True, "tier": tier_of({"pro_until": until})}

    def _rc_transfer(self, event: dict) -> dict:
        """A purchase moved to another app user (a restore on another account): the
        Pro time goes with it."""
        source = [a for a in map(self._rc_account, event.get("transferred_from") or []) if a]
        until = max((a.get("pro_until") or 0 for a in source), default=0) or None
        for a in source:
            self.set_pro_until(a["id"], None)
        for a in map(self._rc_account, event.get("transferred_to") or []):
            if a and until:
                self.set_pro_until(a["id"], max(until, a.get("pro_until") or 0))
        return {"ok": True}

    def _forget_devices(self) -> None:
        with self._cache_lock:
            self._device_cache.clear()


def _public(account: dict) -> dict:
    return {
        "id": account["id"],
        "email": account.get("email"),
        "display_name": account.get("display_name"),
        "provider": account.get("provider"),
        "picture": account.get("picture"),
        "tier": tier_of(account),
    }


# ---- rate limit ----------------------------------------------------------------------


class _Limiter:
    """Sign-ins per client address per minute, in memory (one container)."""

    def __init__(self, per_min: int) -> None:
        self.per_min = per_min
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        # Railway's proxy writes X-Real-IP, and appends the real address LAST in
        # X-Forwarded-For; anything before it the caller could have written.
        forwarded = request.headers.get("x-forwarded-for", "")
        ip = (
            request.headers.get("x-real-ip")
            or (forwarded.split(",")[-1].strip() if forwarded else "")
            or (request.client.host if request.client else "?")
        )
        now = time.time()
        with self.lock:
            # Every address that ever signed in stayed in the map, on a relay anyone can
            # reach: drop the ones idle for a minute whenever the map grows.
            if len(self.hits) > 1024:
                for old in [k for k, v in self.hits.items() if not v or now - v[-1] > 60]:
                    del self.hits[old]
            q = self.hits[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_min:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many sign-ins")
            q.append(now)


# ---- routes ------------------------------------------------------------------------


class GoogleIn(BaseModel):
    id_token: str = Field(max_length=8192)


class GoogleDesktopIn(BaseModel):
    code: str = Field(max_length=2048)
    code_verifier: str = Field(max_length=256)
    redirect_uri: str = Field(max_length=512)


class AppleIn(BaseModel):
    identity_token: str = Field(max_length=8192)
    user_name: str | None = Field(default=None, max_length=255)


class HandoffIn(BaseModel):
    code: str = Field(max_length=128)


def _apple_state(state: str | None) -> tuple[str, str] | None:
    """(return_to, nonce) from the state the Mac sent Apple, or None if it is not ours."""
    try:
        raw = base64.urlsafe_b64decode((state or "") + "=" * (-len(state or "") % 4))
        data = json.loads(raw)
        return_to, nonce = str(data["r"]), str(data["n"])
    except (ValueError, KeyError, TypeError):
        return None
    if not _RETURN_TO.fullmatch(return_to) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", nonce):
        return None
    return return_to, nonce


def _apple_name(user: str | None) -> str | None:
    """The name Apple sends once, on the first sign-in only, as JSON in `user`."""
    try:
        name = json.loads(user or "{}").get("name") or {}
    except (ValueError, AttributeError):
        return None
    full = " ".join(p for p in (name.get("firstName"), name.get("lastName")) if p)
    return full[:255] or None


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=4096)


class DeviceIn(BaseModel):
    name: str = Field(default="device", max_length=100)
    kind: str = Field(default="computer", pattern="^(computer|phone)$")


def router(accounts: Accounts) -> APIRouter:
    r = APIRouter()
    limit = _Limiter(accounts.s.rate_limit_per_min)

    def current(authorization: str = Header(default="")) -> dict:
        scheme, _, token = authorization.partition(" ")
        if scheme != "Bearer" or not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in required")
        return accounts.account_from_access(token)

    def signed_in_or_device(authorization: str = Header(default="")) -> dict:
        """A session (the Mac) or a device token (the phone, which has no session)."""
        scheme, _, token = authorization.partition(" ")
        if scheme == "Bearer" and token.startswith(DEVICE_TOKEN_PREFIX):
            account = accounts.account_for_device(token)
            if account is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "device not linked")
            return account
        return current(authorization)

    @r.post("/auth/google", dependencies=[Depends(limit)])
    def google(body: GoogleIn):
        claims = accounts.verify_google(body.id_token)
        return accounts.issue_pair(accounts.account_for("google", claims))

    @r.post("/auth/google/desktop", dependencies=[Depends(limit)])
    def google_desktop(body: GoogleDesktopIn):
        id_token = accounts.google_desktop_code(body.code, body.code_verifier, body.redirect_uri)
        claims = accounts.verify_google(id_token)
        return accounts.issue_pair(accounts.account_for("google", claims))

    @r.post("/auth/apple", dependencies=[Depends(limit)])
    def apple(body: AppleIn):
        claims = accounts.verify_apple(body.identity_token)
        return accounts.issue_pair(accounts.account_for("apple", claims, body.user_name))

    @r.post("/auth/apple/callback", dependencies=[Depends(limit)])
    def apple_callback(
        id_token: str | None = Form(default=None, max_length=8192),
        user: str | None = Form(default=None, max_length=4096),
        state: str | None = Form(default=None, max_length=1024),
        error: str | None = Form(default=None, max_length=200),
    ):
        """Apple's web flow posts here (response_mode=form_post). The browser is sent
        on to the Mac's engine with a one-time code, never with the session itself."""
        target = _apple_state(state)
        if target is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "not a sign in this relay started")
        return_to, nonce = target
        if error or not id_token:
            # Cancelled in Apple's page: tell the Mac, so it stops waiting.
            return RedirectResponse(f"{return_to}?state={nonce}&error=cancelled", 303)
        claims = accounts.verify_apple(id_token)
        account = accounts.account_for("apple", claims, _apple_name(user))
        code = accounts.start_handoff(account)
        return RedirectResponse(f"{return_to}?state={nonce}&handoff={code}", 303)

    @r.post("/auth/handoff", dependencies=[Depends(limit)])
    def handoff(body: HandoffIn):
        return accounts.redeem_handoff(body.code)

    @r.post("/auth/refresh", dependencies=[Depends(limit)])
    def refresh(body: RefreshIn):
        return accounts.refresh(body.refresh_token)

    @r.post("/auth/logout", status_code=204)
    def logout(body: RefreshIn):
        accounts.logout(body.refresh_token)

    @r.post("/auth/logout-all", status_code=204)
    def logout_all(account: dict = Depends(current)):
        accounts.logout_all(account["id"])

    @r.get("/account")
    def me(account: dict = Depends(current)):
        return {
            **_public(account),
            "has_library": bool(account.get("library_id")),
            "devices": accounts.devices(account["id"]),
            "plan": accounts.plan(account),
        }

    @r.get("/account/plan")
    def plan(account: dict = Depends(signed_in_or_device)):
        return accounts.plan(account)

    @r.post("/account/devices", status_code=201)
    def add_device(body: DeviceIn, account: dict = Depends(current)):
        return accounts.add_device(account, body.name, body.kind)

    @r.post("/webhooks/revenuecat")
    def revenuecat(body: dict, authorization: str = Header(default="")):
        expected = accounts.s.revenuecat_webhook_auth
        if not expected or not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not RevenueCat")
        return accounts.revenuecat(body)

    @r.patch("/account/devices/{device_id}", status_code=204)
    def rename_device(device_id: str, body: DeviceIn, account: dict = Depends(current)):
        if not accounts.rename_device(account["id"], device_id, body.name):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such device")

    @r.delete("/account/devices/{device_id}", status_code=204)
    def revoke_device(device_id: str, account: dict = Depends(current)):
        if not accounts.revoke_device(account["id"], device_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such device")

    @r.delete("/account", status_code=204)
    def delete_me(account: dict = Depends(current)):
        accounts.delete_account(account["id"])

    return r
