"""Token verification. OIDC (RS256/ES256 via JWKS) in staging/production; HS256 dev tokens only in local/test."""
from dataclasses import dataclass, field
from typing import Any

import jwt

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

    def verify(self, token: str) -> Claims:
        """DEV MODE ONLY (HS256). In oidc mode bearer tokens are verified by OidcClient.verify_access_jwt."""
        if self.s.auth_mode != "dev":
            raise Unauthorized("Invalid or expired credentials")
        try:
            data: dict[str, Any] = jwt.decode(token, self.s.dev_jwt_secret, algorithms=["HS256"], audience="vand-dev",
                                              options={"require": ["exp", "sub"]})
        except jwt.PyJWTError:
            raise Unauthorized("Invalid or expired credentials") from None
        amr = data.get("amr") or []
        return Claims(
            subject=str(data["sub"]), email=(data.get("email") or None) and str(data["email"]).lower(),
            email_verified=bool(data.get("email_verified", False)), name=data.get("name"),
            amr=tuple(str(a) for a in amr) if isinstance(amr, list) else ())
