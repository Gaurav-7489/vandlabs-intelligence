# ADR-0004: Managed OIDC authentication (provider not yet selected)
**Status:** partially implemented. The API verifies RS256/ES256 JWTs from a configurable OIDC issuer/JWKS and reads `amr` for MFA. **No identity provider has been
chosen or configured**; the provider decision (organizations, MFA, session model) is open and requires the owner. Local development uses an HS256 dev-token endpoint that is
mounted only when `VAND_AUTH_MODE=dev` and is rejected by config validation in staging/production.
**Known gap:** the SPA keeps the token in memory (reload = re-login). Production should use an authorization-code + PKCE flow or a BFF with HttpOnly session cookies.
