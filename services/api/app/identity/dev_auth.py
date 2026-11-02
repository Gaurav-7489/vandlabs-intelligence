"""LOCAL DEVELOPMENT ONLY. Mounted solely when auth_mode == "dev" (Settings refuses dev mode in staging/production).
Issues HS256 tokens for any email so the UI can be exercised without an identity provider."""
import time

import jwt
from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr

from app.core.state import get_state

router = APIRouter(tags=["dev-auth"])


class DevLogin(BaseModel):
    email: EmailStr
    mfa: bool = True


@router.post("/auth/dev-token")
async def dev_token(body: DevLogin, request: Request):
    s = get_state(request).settings
    now = int(time.time())
    claims = {"sub": f"dev:{body.email.lower()}", "email": body.email.lower(), "email_verified": True, "aud": "vand-dev", "iat": now,
              "exp": now + 8 * 3600, "amr": ["pwd", "mfa"] if body.mfa else ["pwd"]}
    return {"access_token": jwt.encode(claims, s.dev_jwt_secret, algorithm="HS256"), "token_type": "bearer"}
