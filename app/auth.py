"""Identity from a verified token (ADR 0005).

`POST /dev/login` stands in for an identity provider; the part built for real is
the verification boundary: a valid token becomes the `Principal`, anything else
is rejected.
"""

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, get_args

import jwt

from app.settings import Settings

log = logging.getLogger(__name__)

Role = Literal["merchant", "operator"]
ALGORITHM = "HS256"
TOKEN_TTL = timedelta(hours=1)

# Mock operator accounts (role `operator`); every other id logs in as a Merchant.
OPERATORS = frozenset({"operador1", "operador2"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InvalidToken(Exception):
    """Bad signature, malformed, missing claims or expired."""


@dataclass(frozen=True)
class Principal:
    sub: str
    role: Role


@dataclass(frozen=True)
class AuthSettings:
    secret: str
    demo_login: bool = False
    clock: Callable[[], datetime] = field(default=_utc_now)

    @classmethod
    def from_settings(cls, settings: Settings) -> "AuthSettings":
        secret = settings.jwt_secret
        if not secret:
            log.warning("JWT_SECRET is empty: using a random secret, so tokens stop working on restart")
            secret = secrets.token_urlsafe(32)
        return cls(secret=secret, demo_login=settings.demo_login)

    def issue(self, sub: str) -> str:
        """A signed token for `sub`, with its role and a 1 hour expiry."""
        role: Role = "operator" if sub in OPERATORS else "merchant"
        exp = self.clock() + TOKEN_TTL
        return jwt.encode({"sub": sub, "role": role, "exp": int(exp.timestamp())}, self.secret, ALGORITHM)

    def verify(self, token: str) -> Principal:
        """The token's principal; raises `InvalidToken` for any token that isn't valid now."""
        try:
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=[ALGORITHM],
                # Expiry is checked against the injected clock below, not the wall clock.
                options={"verify_exp": False, "require": ["sub", "role", "exp"]},
            )
        except jwt.InvalidTokenError as exc:
            raise InvalidToken(str(exc)) from exc
        sub, role, exp = claims["sub"], claims["role"], claims["exp"]
        if not isinstance(sub, str) or not sub or role not in get_args(Role):
            raise InvalidToken("bad claims")
        if not isinstance(exp, int | float) or exp <= self.clock().timestamp():
            raise InvalidToken("expired")
        return Principal(sub=sub, role=role)
