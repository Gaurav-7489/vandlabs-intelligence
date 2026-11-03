/**
 * Vercel Edge Function: same-origin gateway for /api/v1/* (see vercel.json rewrite and src/edge/proxy.ts).
 *
 * Server-side env vars (Vercel → Project → Settings → Environment Variables, scope **Production only**):
 *   VAND_API_ORIGIN          https://<FastAPI origin>
 *   VAND_ORIGIN_AUTH_SECRET  same value as the API's VAND_ORIGIN_AUTH_SECRET (>= 32 chars). Never prefix with VITE_.
 * Preview/development deployments refuse to proxy unless VAND_GATEWAY_ALLOW_PREVIEW=true is set for that scope,
 * so a preview build can never reach the staging API with the staging secret by accident.
 */
import { jsonError, proxyApi } from "../src/edge/proxy";

export const config = { runtime: "edge" };

export default async function handler(request: Request): Promise<Response> {
  const env = process.env;
  const deployment = env.VERCEL_ENV ?? "development";
  if (deployment !== "production" && env.VAND_GATEWAY_ALLOW_PREVIEW !== "true") {
    return jsonError(503, "gateway_unavailable", "The API is not available on this deployment.");
  }
  // Vercel sets x-real-ip from the TCP peer at its edge and overwrites any client-sent value.
  return proxyApi(request, { apiOrigin: env.VAND_API_ORIGIN ?? "", originAuthSecret: env.VAND_ORIGIN_AUTH_SECRET ?? "" },
    request.headers.get("x-real-ip"));
}
