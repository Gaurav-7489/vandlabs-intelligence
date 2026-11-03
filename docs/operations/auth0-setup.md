# Auth0 setup (exact external configuration still required)

**Staging values (Phase 1.7):** web origin `https://vandlabs-intelligence.vercel.app` → Allowed Callback `https://vandlabs-intelligence.vercel.app/api/v1/auth/callback`, Allowed Logout `https://vandlabs-intelligence.vercel.app/`, Allowed Web Origins `https://vandlabs-intelligence.vercel.app`. Plan: **Free only (A7)**. First check that Security → Multi-factor Auth offers OTP and/or WebAuthn with policy *Always* on the Free tenant (Auth0 docs: available factors depend on the subscription plan); if it does not, stop and request a decision — do not lower `VAND_REQUIRE_MFA_FOR_PRIVILEGED`.
Synthetic users (staging): requester (manager, org A), approver (manager, org A), auditor (auditor, org A), outsider (manager, org B only), owner (owner, org A, MFA enrolled). Create them in Auth0, then add memberships in the app as the platform admin.

**Status:** the application implements a standards-based OIDC Authorization Code + PKCE flow (BFF session) and is tested against a local test issuer. **It has not been run against a real Auth0 tenant** — no tenant/credentials were available. Complete the steps below, then run the verification checklist.

1. **Create a tenant** (separate for staging and production). Enable MFA (Security → Multi-factor Auth: One-time password and/or WebAuthn; policy *Always* or adaptive; confirm your Auth0 plan allows the policy you need).
2. **Regular Web Application** (confidential client): Allowed Callback URL `https://<web-origin>/api/v1/auth/callback`; Allowed Logout URL `https://<web-origin>/`; Allowed Web Origins `https://<web-origin>`. Token endpoint auth: Client Secret (Post). Enable **Refresh Token Rotation** + reuse detection; set absolute/idle lifetimes ≤ the app's session TTLs.
3. **API** (Resource Server) with identifier = `VAND_OIDC_AUDIENCE` (also set `VAND_OIDC_EXTRA_AUTHORIZE_PARAMS=audience=<identifier>`), RS256.
4. **Database connection**: disable open sign-ups (invite-only); require email verification. The app only binds an invited user when `email_verified=true`.
5. **MFA claim**: the app requires `amr` containing `mfa`/`otp`/`hwk` for owner/admin/platform-admin. Auth0 adds `amr: ["mfa"]` to the ID token when MFA was performed in that login; **verify this in your tenant** by decoding a real ID token after an MFA login (and one without MFA: it must NOT contain `mfa`). Only if Auth0 does not emit it, add a post-login Action that derives it **from what actually happened**, never unconditionally:
   ```js
   exports.onExecutePostLogin = async (event, api) => {
     const didMfa = (event.authentication?.methods ?? []).some((m) => m.name === "mfa");
     if (didMfa) api.idToken.setCustomClaim("amr", ["mfa"]);   // never set it when MFA did not happen
   };
   ```
   An Action that sets `amr` whenever it is "missing" would fake MFA and defeat the owner/admin requirement.
6. **Invitations**: the owner adds the member in the app (`POST /members`); the invitee follows `https://<web-origin>/?invite=1&email=<address>` (sign-up screen hint), verifies the email, and the identity is bound on first login. Auth0 Organizations are not used yet.
7. **Secrets**: `VAND_OIDC_CLIENT_ID/SECRET`, `VAND_SESSION_ENCRYPTION_KEY` (`python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`), `VAND_ORIGIN_AUTH_SECRET` (≥32 random chars) → secret manager, never Git.

## Verification checklist (do in staging)
Sign in; refresh stays signed in; sign out ends the IdP session; owner without MFA is blocked; block a user in Auth0 → session ends within `VAND_SESSION_REVALIDATE_SECONDS` (default 900 s); `/me` shows memberships; cross-org header is denied; ID token `aud`=client id, access token `aud`=API identifier; JWKS rotation works.

## Known limits
Revocation latency is bounded by the revalidation interval (and an IdP outage keeps existing sessions until it recovers — chosen over mass logout). Enterprise SSO (SAML/OIDC connections) needs no app change but needs Auth0 plan support and per-tenant domain routing (not built).
