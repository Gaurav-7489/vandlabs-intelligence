import { useState, type FormEvent } from "react";
import { useSession } from "../lib/session";

export default function Login() {
  const { signIn, error, loading } = useSession();
  const [email, setEmail] = useState("");
  const [mfa, setMfa] = useState(true);
  const submit = (e: FormEvent) => { e.preventDefault(); void signIn(email.trim().toLowerCase(), mfa); };
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <form onSubmit={submit} className="card enter w-full max-w-sm space-y-5 p-6" aria-labelledby="t">
        <div>
          <p className="font-display text-3xl" id="t">VandLabs Intelligence</p>
          <p className="mt-1 text-sm text-ink2">Evidence, decisions and verified action for your organization.</p>
        </div>
        <div className="rounded-lg border border-line bg-warnsoft p-3 text-xs text-warn" role="note">
          Local development sign-in. Production uses your organization's OIDC identity provider; this form is disabled there.
        </div>
        <div>
          <label className="label" htmlFor="email">Work email</label>
          <input id="email" className="input" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={mfa} onChange={(e) => setMfa(e.target.checked)} /> Simulate MFA-verified session</label>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <button className="btn btn-primary w-full" disabled={loading || !email}>{loading ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}
