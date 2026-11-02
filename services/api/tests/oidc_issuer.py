"""A minimal, in-process OIDC provider for tests (Authorization Code + PKCE, refresh rotation, JWKS). NOT for production."""
import base64
import os
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

ISSUER = os.environ.get("TEST_ISSUER", "https://idp.test")
CLIENT_ID, CLIENT_SECRET, API_AUD = "vand-web", "s3cret", "https://api.vand.test"


def _jwk(pub: Any, kid: str) -> dict[str, Any]:
    d = jwt.algorithms.RSAAlgorithm.to_jwk(pub, as_dict=True)
    return {**d, "kid": kid, "use": "sig", "alg": "RS256"}


class TestIssuer:
    __test__ = False

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "k1"
        self.codes: dict[str, dict[str, Any]] = {}
        self.refresh: dict[str, dict[str, Any]] = {}
        self.revoked: set[str] = set()  # refresh tokens the "IdP admin" has revoked
        self.idp_down = False
        self.id_overrides: dict[str, Any] = {}  # e.g. {"aud": "other"} / {"iss": ...} / {"exp": past}
        self.sign_with_rogue = False
        self.app = self._build()

    def sign(self, claims: dict[str, Any], rogue: bool = False) -> str:
        return jwt.encode(claims, self.rogue_key if rogue else self.key, algorithm="RS256", headers={"kid": self.kid})

    def access_jwt(self, email: str, aud: str = API_AUD, iss: str = ISSUER, exp_in: int = 600, mfa: bool = True, rogue: bool = False) -> str:
        now = int(time.time())
        return self.sign({"iss": iss, "aud": aud, "sub": f"auth0|{email}", "email": email, "email_verified": True, "iat": now, "exp": now + exp_in,
                          "amr": ["pwd", "mfa"] if mfa else ["pwd"]}, rogue)

    def _id_token(self, rec: dict[str, Any]) -> str:
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": f"auth0|{rec['email']}", "email": rec["email"], "email_verified": rec.get("verified", True),
                  "name": rec["email"].split("@")[0], "nonce": rec["nonce"], "iat": now, "exp": now + 600, "amr": ["pwd", "mfa"] if rec["mfa"] else ["pwd"]}
        claims.update(self.id_overrides)
        return self.sign(claims, self.sign_with_rogue)

    def _build(self) -> FastAPI:
        app = FastAPI()
        me = self

        @app.get("/.well-known/openid-configuration")
        async def disc():
            if me.idp_down:
                return JSONResponse({}, status_code=503)
            return {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize", "token_endpoint": f"{ISSUER}/oauth/token",
                    "jwks_uri": f"{ISSUER}/jwks.json", "end_session_endpoint": f"{ISSUER}/logout"}

        @app.get("/jwks.json")
        async def jwks():
            return {"keys": [_jwk(me.key.public_key(), me.kid)]}

        @app.get("/authorize")
        async def authorize(request: Request):
            q = request.query_params
            if "sim_user" not in q:  # interactive mode for browser E2E: a tiny login form
                fields = "".join(f'<input type="hidden" name="{k}" value="{v}">' for k, v in q.items())
                return HTMLResponse(f"""<!doctype html><html lang=en><title>Test IdP</title><form method=get action=/authorize>{fields}
                  <label>Email <input name=sim_user type=email required></label>
                  <input type=hidden name=sim_mfa value=0><label><input type=checkbox name=sim_mfa value=1 checked> MFA</label><button>Sign in</button></form>""")
            code = secrets.token_urlsafe(16)
            me.codes[code] = {"email": q["sim_user"], "mfa": q.get("sim_mfa", "1") == "1", "nonce": q["nonce"], "challenge": q["code_challenge"],
                              "verified": q.get("sim_verified", "1") == "1", "redirect_uri": q["redirect_uri"]}
            return RedirectResponse(f"{q['redirect_uri']}?{urlencode({'code': code, 'state': q['state']})}", status_code=302)

        @app.get("/logout")
        async def logout(request: Request):
            return RedirectResponse(request.query_params.get("post_logout_redirect_uri", "/"), status_code=302)

        @app.post("/oauth/token")
        async def token(grant_type: str = Form(), client_id: str = Form(), client_secret: str = Form(), code: str | None = Form(None),
                        code_verifier: str | None = Form(None), refresh_token: str | None = Form(None), redirect_uri: str | None = Form(None)):
            if me.idp_down:
                return JSONResponse({"error": "server_error"}, status_code=503)
            if client_id != CLIENT_ID or client_secret != CLIENT_SECRET:
                return JSONResponse({"error": "invalid_client"}, status_code=401)
            if grant_type == "authorization_code":
                rec = me.codes.pop(code or "", None)  # single use
                if rec is None:
                    return JSONResponse({"error": "invalid_grant"}, status_code=400)
                chal = base64.urlsafe_b64encode(hashlib.sha256((code_verifier or "").encode()).digest()).rstrip(b"=").decode()
                if chal != rec["challenge"] or redirect_uri != rec["redirect_uri"]:
                    return JSONResponse({"error": "invalid_grant"}, status_code=400)
            elif grant_type == "refresh_token":
                rec = me.refresh.pop(refresh_token or "", None)
                if rec is None or refresh_token in me.revoked:
                    return JSONResponse({"error": "invalid_grant"}, status_code=400)
            else:
                return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
            new_rt = "rt-" + secrets.token_urlsafe(16)
            me.refresh[new_rt] = rec
            return {"id_token": me._id_token(rec), "access_token": "opaque-at", "refresh_token": new_rt, "expires_in": 600, "token_type": "Bearer"}

        return app
