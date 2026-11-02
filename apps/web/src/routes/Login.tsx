import { useState, type FormEvent } from "react";
import { useSession } from "../lib/session";

const ERRORS: Record<string, string> = {
  login_failed: "We couldn't verify your sign-in. Please try again.",
  idp_unavailable: "The identity provider is temporarily unavailable. Please try again shortly.",
};

function Shell({ children, subtitle }: { children: React.ReactNode; subtitle: string }) {
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="card enter w-full max-w-sm space-y-5 p-6">
        <div><p className="font-display text-3xl">VandLabs Intelligence</p><p className="mt-1 text-sm text-ink2">{subtitle}</p></div>
        {children}
      </div>
    </main>
  );
}

export default function Login() {
  const { mode, signIn, error, loading, notice } = useSession();
  const [email, setEmail] = useState("");
  const [mfa, setMfa] = useState(true);
  const params = new URLSearchParams(window.location.search);
  const authError = ERRORS[params.get("auth_error") ?? ""];
  const invited = params.get("invite") === "1";
  const inviteEmail = params.get("email") ?? "";
  const returnTo = window.location.pathname + (invited ? "" : "");
  const go = (extra: string) => window.location.assign(`/api/v1/auth/login?return_to=${encodeURIComponent(returnTo === "/" ? "/" : returnTo)}${extra}`);

  if (mode === "oidc") {
    return (
      <Shell subtitle={invited ? "You've been invited to join your organization." : "Evidence, decisions and verified action for your organization."}>
        {(notice || authError) && <p role="alert" className="rounded-lg bg-warnsoft p-3 text-sm text-warn">{notice ?? authError}</p>}
        {invited ? (
          <>
            <p className="text-sm text-ink2">Create your account with {inviteEmail ? <strong>{inviteEmail}</strong> : "the email address you were invited with"}. You must verify that email address to join.</p>
            <button className="btn btn-primary w-full" onClick={() => go(`&screen_hint=signup${inviteEmail ? `&login_hint=${encodeURIComponent(inviteEmail)}` : ""}`)}>Accept invitation</button>
            <button className="btn w-full" onClick={() => go("")}>I already have an account</button>
          </>
        ) : <button className="btn btn-primary w-full" onClick={() => go("")}>Continue to sign in</button>}
        <p className="text-xs text-ink3">You'll be redirected to your organization's secure sign-in. Multi-factor authentication may be required for administrators.</p>
      </Shell>
    );
  }
  const submit = (e: FormEvent) => { e.preventDefault(); void signIn(email.trim().toLowerCase(), mfa); };
  return (
    <Shell subtitle="Evidence, decisions and verified action for your organization.">
      <form onSubmit={submit} className="space-y-5">
        <div className="rounded-lg border border-line bg-warnsoft p-3 text-xs text-warn" role="note">Local development sign-in. Production uses OIDC; this form does not exist there.</div>
        {notice && <p role="alert" className="text-sm text-warn">{notice}</p>}
        <div><label className="label" htmlFor="email">Work email</label>
          <input id="email" className="input" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={mfa} onChange={(e) => setMfa(e.target.checked)} /> Simulate MFA-verified session</label>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <button className="btn btn-primary w-full" disabled={loading || !email}>{loading ? "Signing in…" : "Sign in"}</button>
      </form>
    </Shell>
  );
}
