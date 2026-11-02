import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setOrg, setToken, setUnauthorizedHandler, type Me, type Membership } from "./api";

interface Session {
  me: Me | null; membership: Membership | null; signIn: (email: string, mfa: boolean) => Promise<void>; signOut: () => void;
  switchOrg: (orgId: string) => void; can: (perm: string) => boolean; error: string | null; loading: boolean;
}
const Ctx = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [me, setMe] = useState<Me | null>(null);
  const [orgId, setOrgId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const signOut = useCallback(() => { setToken(null); setOrg(null); setMe(null); setOrgId(null); qc.clear(); }, [qc]);
  useEffect(() => setUnauthorizedHandler(signOut), [signOut]);

  const signIn = useCallback(async (email: string, mfa: boolean) => {
    setLoading(true); setError(null);
    try {
      const t = await api<{ access_token: string }>("/auth/dev-token", { method: "POST", body: { email, mfa }, org: false });
      setToken(t.access_token);
      const m = await api<Me>("/me", { org: false });
      qc.clear();
      const first = m.memberships[0]?.org_id ?? null;
      setOrg(first); setOrgId(first); setMe(m);
    } catch (e) { setToken(null); setError(e instanceof Error ? e.message : "Sign-in failed"); } finally { setLoading(false); }
  }, [qc]);

  const switchOrg = useCallback((id: string) => { setOrg(id); setOrgId(id); qc.clear(); }, [qc]); // clear caches: no cross-tenant cache reuse
  const membership = useMemo(() => me?.memberships.find((m) => m.org_id === orgId) ?? null, [me, orgId]);
  const can = useCallback((p: string) => !!membership?.permissions.includes(p), [membership]);
  const value = useMemo(() => ({ me, membership, signIn, signOut, switchOrg, can, error, loading }), [me, membership, signIn, signOut, switchOrg, can, error, loading]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const v = useContext(Ctx);
  if (!v) throw new Error("SessionProvider missing");
  return v;
}
// Query keys are namespaced by org so cached data can never be served across tenants.
export const useOrgKey = () => useSession().membership?.org_id ?? "none";
