"""OIDC relying-party logic: discovery, JWKS (with rotation), PKCE code exchange, refresh, id/access-token validation.

All network I/O goes through an injectable httpx.AsyncClient so tests can use a local test issuer."""
import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import Settings
from app.core.errors import Unauthorized
from app.core.logging import get_logger
from app.identity.tokens import Claims

log = get_logger("oidc")
_ALGS = ["RS256", "ES256"]


class OidcError(Exception):
    """Token endpoint / validation failure. `permanent` = the grant is no longer valid (e.g. invalid_grant)."""

    def __init__(self, msg: str, permanent: bool = True):
        super().__init__(msg)
        self.permanent = permanent


@dataclass
class TokenSet:
    id_token: str
    access_token: str | None
    refresh_token: str | None
    expires_in: int


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class OidcClient:
    def __init__(self, s: Settings, http: httpx.AsyncClient | None = None):
        self.s = s
        self.http = http or httpx.AsyncClient(timeout=10.0)
        self._disc: dict[str, Any] | None = None
        self._jwks: dict[str, Any] = {}
        self._jwks_at = 0.0
        self._jwks_refetch_at = 0.0

    async def _discovery(self) -> dict[str, Any]:
        if self._disc is None:
            if self.s.oidc_authorize_url and self.s.oidc_token_url:
                self._disc = {"authorization_endpoint": self.s.oidc_authorize_url, "token_endpoint": self.s.oidc_token_url,
                              "jwks_uri": self.s.oidc_jwks_url, "end_session_endpoint": self.s.oidc_end_session_url or None}
            else:
                r = await self.http.get(self.s.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration")
                r.raise_for_status()
                self._disc = r.json()
                if self._disc.get("issuer", "").rstrip("/") != self.s.oidc_issuer.rstrip("/"):
                    self._disc = None
                    raise OidcError("discovery issuer mismatch")
        return self._disc

    async def _key(self, kid: str | None) -> Any:
        now = time.monotonic()
        if (kid or "") not in self._jwks and (now - self._jwks_at > 3600 or (now - self._jwks_refetch_at > 30)):
            # unknown kid => possible key rotation; refetch at most every 30s (prevents JWKS-fetch amplification)
            self._jwks_refetch_at = now
            r = await self.http.get(self.s.oidc_jwks_url or (await self._discovery())["jwks_uri"])
            r.raise_for_status()
            self._jwks = {k.get("kid"): k for k in r.json()["keys"]}
            self._jwks_at = now
        jwk = self._jwks.get(kid or "")
        if jwk is None:
            raise OidcError("unknown signing key")
        return jwt.PyJWK.from_dict(jwk).key

    async def _decode(self, token: str, audience: str, nonce: str | None = None) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in _ALGS:
                raise OidcError("disallowed algorithm")
            key = await self._key(header.get("kid"))
            data: dict[str, Any] = jwt.decode(token, key, algorithms=_ALGS, audience=audience, issuer=self.s.oidc_issuer,
                                              options={"require": ["exp", "iss", "aud", "sub"]})
        except jwt.PyJWTError as e:
            raise OidcError(f"invalid token: {type(e).__name__}") from None
        if nonce is not None and not secrets.compare_digest(str(data.get("nonce", "")), nonce):
            raise OidcError("nonce mismatch")
        return data

    def to_claims(self, data: dict[str, Any]) -> Claims:
        amr = data.get("amr") or []
        email = data.get("email")
        return Claims(subject=str(data["sub"]), email=str(email).lower() if email else None, email_verified=data.get("email_verified") is True,
                      name=data.get("name"), amr=tuple(str(a) for a in amr) if isinstance(amr, list) else ())

    async def verify_id_token(self, token: str, nonce: str) -> Claims:
        return self.to_claims(await self._decode(token, self.s.oidc_client_id, nonce))

    async def verify_access_jwt(self, token: str) -> Claims:
        """Bearer JWTs presented directly to the API (machine clients). Audience must be the API audience."""
        try:
            return self.to_claims(await self._decode(token, self.s.oidc_audience))
        except OidcError:
            raise Unauthorized("Invalid or expired credentials") from None

    async def authorize_url(self, *, state: str, nonce: str, challenge: str, extra: dict[str, str] | None = None) -> str:
        d = await self._discovery()
        params = {"response_type": "code", "client_id": self.s.oidc_client_id, "redirect_uri": f"{self.s.public_base_url.rstrip('/')}/api/v1/auth/callback",
                  "scope": self.s.oidc_scopes, "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
        for pair in filter(None, self.s.oidc_extra_authorize_params.split("&")):
            k, _, v = pair.partition("=")
            params[k] = v
        params.update(extra or {})
        return f"{d['authorization_endpoint']}?{urlencode(params)}"

    async def _token_request(self, form: dict[str, str]) -> TokenSet:
        d = await self._discovery()
        try:
            r = await self.http.post(d["token_endpoint"], data={**form, "client_id": self.s.oidc_client_id, "client_secret": self.s.oidc_client_secret})
        except httpx.HTTPError as e:
            raise OidcError(f"token endpoint unreachable: {type(e).__name__}", permanent=False) from None
        if r.status_code >= 500:
            raise OidcError("token endpoint error", permanent=False)
        if r.status_code != 200:
            raise OidcError(f"token request rejected: {r.json().get('error', 'error') if r.headers.get('content-type', '').startswith('application/json') else 'error'}")
        j = r.json()
        return TokenSet(j.get("id_token", ""), j.get("access_token"), j.get("refresh_token"), int(j.get("expires_in", 0)))

    async def exchange_code(self, code: str, verifier: str) -> TokenSet:
        return await self._token_request({"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                                          "redirect_uri": f"{self.s.public_base_url.rstrip('/')}/api/v1/auth/callback"})

    async def refresh(self, refresh_token: str) -> TokenSet:
        return await self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    async def end_session_url(self, id_token_hint: str | None) -> str | None:
        ep = (await self._discovery()).get("end_session_endpoint")
        if not ep:
            return None
        q = {"client_id": self.s.oidc_client_id, "post_logout_redirect_uri": self.s.public_base_url.rstrip("/") + "/"}
        if id_token_hint:
            q["id_token_hint"] = id_token_hint
        return f"{ep}?{urlencode(q)}"
