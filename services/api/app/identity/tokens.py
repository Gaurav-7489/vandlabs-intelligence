"""Token verification. OIDC (RS256/ES256 via JWKS) in staging/production; HS256 dev tokens only in local/test."""
from dataclasses import dataclass, field
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import Settings
from app.core.errors import Unauthorized


@dataclass(frozen=True)
class Claims:
    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    amr: tuple[str, ...] = field(default_factory=tuple)

    @property
    def mfa(self) -> bool:
        return "mfa" in self.amr or "otp" in self.amr or "hwk" in self.amr


class TokenVerifier:
    def __init__(self, settings: Settings):
        self.s = settings
        self._jwks = PyJWKClient(settings.oidc_jwks_url, cache_keys=True, lifespan=3600) if settings.auth_mode == "oidc" else None

    def verify(self, token: str) -> Claims:
        try:
            if self.s.auth_mode == "dev":
                data: dict[str, Any] = jwt.decode(
                    token, self.s.dev_jwt_secret, algorithms=["HS256"], audience="vand-dev",
                    options={"require": ["exp", "sub"]})
            else:
                assert self._jwks is not None
                key = self._jwks.get_signing_key_from_jwt(token).key
                data = jwt.decode(
                    token, key, algorithms=["RS256", "ES256"], audience=self.s.oidc_audience, issuer=self.s.oidc_issuer,
                    options={"require": ["exp", "sub", "iss", "aud"]})
        except jwt.PyJWTError:
            raise Unauthorized("Invalid or expired credentials") from None
        amr = data.get("amr") or []
        return Claims(
            subject=str(data["sub"]), email=(data.get("email") or None) and str(data["email"]).lower(),
            email_verified=bool(data.get("email_verified", False)), name=data.get("name"),
            amr=tuple(str(a) for a in amr) if isinstance(amr, list) else ())
