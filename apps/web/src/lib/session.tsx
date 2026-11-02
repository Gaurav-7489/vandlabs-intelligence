import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setCsrf, setMfaHandler, setOrg, setToken, setUnauthorizedHandler, type Me, type Membership } from "./api";

type Status = "loading" | "anon" | "authed";
interface Session {
  status: Status; mode: "dev" | "oidc"; me: Me | null; membership: Membership | null; notice: string | null; mfaRequired: boolean;
  signIn: (email: string, mfa: boolean) => Promise<void>; signOut: () => Promise<void>; switchOrg: (orgId: string) => void;
  can: (perm: string) => boolean; error: string | null; loading: boolean;
}
const Ctx = createContext<Session | null>(null);
const ORG_KEY = "vand-org"; // an organization id is not a secret; it only remembers the last selection across refreshes

const readOrg = () => { try { return sessionStorage.getItem(ORG_KEY); } catch { return null; } };
const writeOrg = (id: string | null) => { try { if (id) sessionStorage.setItem(ORG_KEY, id); else sessionStorage.removeItem(ORG_KEY); } catch { /* optional */ } };

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<Status>("loading");
  const [mode, setMode] = useState<"dev" | "oidc">("oidc");
  const [me, setMe] = useState<Me | null>(null);
  const [orgId, setOrgId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [loading, setLoading] = useState(false);

  const reset = useCallback((why: string | null) => {
    setToken(null); setCsrf(null); setOrg(null); setMe(null); setOrgId(null); setMfaRequired(false); writeOrg(null);
    qc.clear(); // sign-out/expiry must never leave one user's organization data in memory for the next
    setNotice(why); setStatus("anon");
  }, [qc]);

  const load = useCallback(async () => {
    const m = await api<Me>("/me", { org: false });
    const remembered = readOrg();
    const pick = m.memberships.find((x) => x.org_id === remembered)?.org_id ?? m.memberships[0]?.org_id ?? null;
    setOrg(pick); setOrgId(pick); writeOrg(pick); setMe(m); setStatus("authed");
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => reset("Your session has expired. Please sign in again."));
    setMfaHandler(() => setMfaRequired(true));
  }, [reset]);

  // Session restoration on first load (and after a browser refresh): ask the server; the cookie is HttpOnly.
  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      try {
        const cfg = await api<{ mode: "dev" | "oidc" }>("/auth/config", { org: false, signal: ac.signal });
        setMode(cfg.mode);
        if (cfg.mode === "oidc") {
          const s = await api<{ authenticated: boolean; csrf?: string }>("/auth/session", { org: false, signal: ac.signal });
          if (s.authenticated && s.csrf) { setCsrf(s.csrf); await load(); return; }
        }
        setStatus("anon");
      } catch { if (!ac.signal.aborted) setStatus("anon"); }
    })();
    return () => ac.abort();
  }, [load]);

  const signIn = useCallback(async (email: string, mfa: boolean) => { // development mode only
    setLoading(true); setError(null);
    try {
      const t = await api<{ access_token: string }>("/auth/dev-token", { method: "POST", body: { email, mfa }, org: false });
      setToken(t.access_token); qc.clear(); await load();
    } catch (e) { setToken(null); setError(e instanceof Error ? e.message : "Sign-in failed"); } finally { setLoading(false); }
  }, [qc, load]);

  const signOut = useCallback(async () => {
    let logoutUrl: string | null = null;
    try { logoutUrl = (await api<{ logout_url: string | null }>("/auth/logout", { method: "POST" })).logout_url; } catch { /* already signed out */ }
    reset(null);
    if (logoutUrl) window.location.assign(logoutUrl);
  }, [reset]);

  const switchOrg = useCallback((id: string) => { setOrg(id); setOrgId(id); writeOrg(id); setMfaRequired(false); qc.clear(); }, [qc]);
  const membership = useMemo(() => me?.memberships.find((m) => m.org_id === orgId) ?? null, [me, orgId]);
  const can = useCallback((p: string) => !!membership?.permissions.includes(p), [membership]);
  const value = useMemo(() => ({ status, mode, me, membership, notice, mfaRequired, signIn, signOut, switchOrg, can, error, loading }),
    [status, mode, me, membership, notice, mfaRequired, signIn, signOut, switchOrg, can, error, loading]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const v = useContext(Ctx);
  if (!v) throw new Error("SessionProvider missing");
  return v;
}
// Query keys are namespaced by org so cached data can never be served across tenants.
export const useOrgKey = () => useSession().membership?.org_id ?? "none";
