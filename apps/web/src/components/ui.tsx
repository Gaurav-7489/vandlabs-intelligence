import { Component, createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { ApiError } from "../lib/api";

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function SkeletonRows({ n = 4 }: { n?: number }) {
  return (
    <div className="space-y-3 p-4" role="status" aria-label="Loading">
      {Array.from({ length: n }, (_, i) => <Skeleton key={i} className="h-5 w-full" />)}
    </div>
  );
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return `Too many requests. Try again in ${e.retryAfter ?? "a few"} seconds.`;
    if (e.status === 403) return e.message || "You do not have access to this.";
    return e.message;
  }
  return "Something went wrong. Please try again.";
}

/** A failed widget never takes down the page: it shows a message and a retry action. */
export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 p-4 text-sm">
      <p className="text-danger">{errorText(error)}</p>
      {onRetry && <button className="btn" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="enter flex flex-col items-center gap-2 px-6 py-12 text-center">
      <p className="font-display text-lg">{title}</p>
      {hint && <p className="max-w-md text-sm text-ink2">{hint}</p>}
      {action}
    </div>
  );
}

export function Badge({ tone, children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge ${tone ? `badge-${tone}` : ""}`}>{children}</span>;
}

export const sevTone = (s: string) => (s === "high" ? "high" : s === "medium" ? "medium" : "low");
export const stateTone = (s: string) => (["completed", "outcome_measured", "closed", "approved", "done", "succeeded"].includes(s) ? "ok"
  : ["rejected", "failed", "blocked", "dead_letter", "quarantined"].includes(s) ? "high" : ["awaiting_approval", "requires_review", "in_progress", "scan_pending"].includes(s) ? "medium" : "accent");

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="font-display text-3xl tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink2">{subtitle}</p>}
      </div>
      {actions}
    </header>
  );
}

export function Card({ title, children, actions, className = "" }: { title?: string; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {title && (
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>{actions}
        </div>
      )}
      {children}
    </section>
  );
}

// ---- Toasts: only ever shown after the server confirms an action. ----
type Toast = { id: number; kind: "ok" | "error"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => undefined);
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((t) => [...t, { id, kind, text }]);
    setTimeout(() => setItems((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2" aria-live="polite" role="status">
        {items.map((t) => (
          <div key={t.id} className={`enter card px-4 py-3 text-sm ${t.kind === "error" ? "border-danger text-danger" : ""}`}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export class Boundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) { return { err }; }
  render() {
    if (!this.state.err) return this.props.children;
    return <ErrorPanel error={this.state.err} onRetry={() => this.setState({ err: null })} />;
  }
}
