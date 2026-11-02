import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Boundary, SkeletonRows } from "../components/ui";
import { useSession } from "../lib/session";
import { useTheme } from "../lib/theme";

const NAV: { to: string; label: string; icon: string; perm?: string }[] = [
  { to: "/", label: "Overview", icon: "M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" },
  { to: "/ask", label: "Ask Intelligence", icon: "M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z", perm: "ai.ask" },
  { to: "/knowledge", label: "Knowledge", icon: "M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4z", perm: "documents.read" },
  { to: "/insights", label: "Insights", icon: "M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4z", perm: "insights.read" },
  { to: "/decisions", label: "Decisions", icon: "M5 12l5 5L20 7", perm: "decisions.read" },
  { to: "/tasks", label: "Tasks", icon: "M4 6h16M4 12h16M4 18h10", perm: "tasks.read" },
  { to: "/integrations", label: "Integrations", icon: "M8 8h8v8H8zM4 12h4M16 12h4M12 4v4M12 16v4", perm: "documents.read" },
  { to: "/admin", label: "Administration", icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 0 0-2-1.2L14 3h-4l-.6 2.6a7 7 0 0 0-2 1.2l-2.3-.9-2 3.4 2 1.5a7 7 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-.9a7 7 0 0 0 2 1.2L10 21h4l.6-2.6a7 7 0 0 0 2-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z", perm: "members.read" },
];

function Icon({ d }: { d: string }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>;
}

export default function Shell() {
  const { me, membership, switchOrg, signOut, can } = useSession();
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  useEffect(() => { document.title = "VandLabs Intelligence"; }, []);

  const nav = (
    <nav aria-label="Primary" className="flex flex-col gap-1">
      {NAV.filter((n) => !n.perm || can(n.perm)).map((n) => (
        <NavLink key={n.to} to={n.to} end={n.to === "/"} className="nav-link"><Icon d={n.icon} />{n.label}</NavLink>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[260px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:p-2">Skip to content</a>
      <aside className="hidden border-r border-line bg-surface p-4 lg:flex lg:flex-col lg:gap-6" aria-label="Sidebar">
        <div className="flex items-center gap-2 px-2 pt-1">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-accentink font-display text-lg" aria-hidden="true">V</span>
          <span className="font-display text-lg leading-tight">VandLabs<br /><span className="text-xs font-sans text-ink3">Intelligence</span></span>
        </div>
        {nav}
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button className="absolute inset-0 bg-black/40" aria-label="Close navigation" onClick={() => setOpen(false)} />
          <div className="enter absolute left-0 top-0 h-full w-72 bg-surface p-4">{nav}</div>
        </div>
      )}

      <div className="flex min-w-0 flex-col">
        <div className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-canvas/90 px-4 py-2.5 backdrop-blur sm:px-6">
          <button className="btn lg:hidden" aria-label="Open navigation" aria-expanded={open} onClick={() => setOpen(true)}>☰</button>
          <div className="min-w-0 flex-1">
            {me && me.memberships.length > 1 ? (
              <select className="input max-w-xs" aria-label="Organization" value={membership?.org_id} onChange={(e) => switchOrg(e.target.value)}>
                {me.memberships.map((m) => <option key={m.org_id} value={m.org_id}>{m.org_name}</option>)}
              </select>
            ) : <p className="truncate text-sm font-medium">{membership?.org_name}</p>}
          </div>
          <span className="badge badge-accent hidden sm:inline-flex">{membership?.role}</span>
          <button className="btn" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>{theme === "dark" ? "☀" : "☾"}</button>
          <button className="btn" onClick={signOut}>Sign out</button>
        </div>
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 sm:py-8" tabIndex={-1}>
          <Boundary key={loc.pathname}>
            <Suspense fallback={<SkeletonRows n={6} />}><Outlet /></Suspense>
          </Boundary>
        </main>
      </div>
    </div>
  );
}
