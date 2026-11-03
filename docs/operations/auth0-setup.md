# Auth0 setup (exact external configuration still required)

**Status:** the application implements a standards-based OIDC Authorization Code + PKCE flow (BFF session) and is tested against a local test issuer. **It has not been run against a real Auth0 tenant** — no tenant/credentials were available. Complete the steps below, then run the verification checklist.

1. **Create a tenant** (separate for staging and production). Enable MFA (Security → Multi-factor Auth: One-time password and/or WebAuthn; policy *Always* or adaptive; confirm your Auth0 plan allows the policy you need).
2. **Regular Web Application** (confidential client): Allowed Callback URL `https://<web-origin>/api/v1/auth/callback`; Allowed Logout URL `https://<web-origin>/`; Allowed Web Origins `https://<web-origin>`. Token endpoint auth: Client Secret (Post). Enable **Refresh Token Rotation** + reuse detection; set absolute/idle lifetimes ≤ the app's session TTLs.
3. **API** (Resource Server) with identifier = `VAND_OIDC_AUDIENCE` (also set `VAND_OIDC_EXTRA_AUTHORIZE_PARAMS=audience=<identifier>`), RS256.
4. **Database connection**: disable open sign-ups (invite-only); require email verification. The app only binds an invited user when `email_verified=true`.
5. **MFA claim**: the app requires `amr` containing `mfa`/`otp`/`hwk` for owner/admin/platform-admin. Auth0 adds `amr` to the ID token when MFA is performed; **verify this in your tenant** (add a post-login Action that sets `api.idToken.setCustomClaim("amr", …)` only if it is missing).
6. **Invitations**: the owner adds the member in the app (`POST /members`); the invitee follows `https://<web-origin>/?invite=1&email=<address>` (sign-up screen hint), verifies the email, and the identity is bound on first login. Auth0 Organizations are not used yet.
7. **Secrets**: `VAND_OIDC_CLIENT_ID/SECRET`, `VAND_SESSION_ENCRYPTION_KEY` (`python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`), `VAND_ORIGIN_AUTH_SECRET` (≥32 random chars) → secret manager, never Git.

## Verification checklist (do in staging)
Sign in; refresh stays signed in; sign out ends the IdP session; owner without MFA is blocked; block a user in Auth0 → session ends within `VAND_SESSION_REVALIDATE_SECONDS` (default 900 s); `/me` shows memberships; cross-org header is denied; ID token `aud`=client id, access token `aud`=API identifier; JWKS rotation works.

## Known limits
Revocation latency is bounded by the revalidation interval (and an IdP outage keeps existing sessions until it recovers — chosen over mass logout). Enterprise SSO (SAML/OIDC connections) needs no app change but needs Auth0 plan support and per-tenant domain routing (not built).
