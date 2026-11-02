/** Typed API client. The bearer token lives in memory only (never localStorage); org context is sent per request
 *  but is only a *request* - the server validates membership and derives the role itself. */
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public retryAfter?: number, public requestId?: string) {
    super(message);
  }
}

let token: string | null = null;
let orgId: string | null = null;
let onUnauthorized: (() => void) | null = null;
export const setToken = (t: string | null) => { token = t; };
export const setOrg = (o: string | null) => { orgId = o; };
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };
export const hasToken = () => token !== null;

type Opts = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal; params?: Record<string, string | number | undefined | null>; headers?: Record<string, string>; org?: boolean };

export async function api<T>(path: string, opts: Opts = {}): Promise<T> {
  const url = new URL(`/api/v1${path}`, window.location.origin);
  for (const [k, v] of Object.entries(opts.params ?? {})) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (orgId && opts.org !== false) headers["X-Org-ID"] = orgId;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  const res = await fetch(url, { method: opts.method ?? "GET", headers, body, signal: opts.signal });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error ?? {};
    if (res.status === 401 && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, e.code ?? "error", e.message ?? res.statusText, Number(res.headers.get("retry-after")) || undefined, e.request_id);
  }
  return data as T;
}

// ---- Types mirror the backend response shapes (hand-maintained; see docs/api for the contract). ----
export type Severity = "high" | "medium" | "low";
export interface Membership { org_id: string; org_name: string; role: string; permissions: string[] }
export interface Me { user: { id: string; email: string; display_name: string | null; is_platform_admin: boolean; mfa: boolean }; memberships: Membership[] }
export interface Page<T> { items: T[]; next_cursor: string | null }
export interface Evidence { type: "commitment" | "task"; id: string; key: string; document_id: string | null; locator: string | null; facts: Record<string, unknown> }
export interface Insight { id: string; rule: string; severity: Severity; status: string; title: string; summary: string; evidence: Evidence[];
  uncertainty: string; recommended_step: string; explanation: string | null; explanation_source: string | null; created_at: string }
export interface Doc { id: string; filename: string; type: string; size_bytes: number; status: string; error: string | null; stats: Record<string, unknown>; created_at: string; duplicate?: boolean }
export interface Decision { id: string; insight_id: string | null; title: string; business_question: string; observation: string; evidence: Evidence[];
  alternatives: { option: string; note: string }[]; recommended_action: { type: string; title: string }; risks: string; success_criteria: string;
  state: string; requested_by: string; created_at: string;
  approvals?: { id: string; action: string; comment: string; created_at: string; actor_user_id: string }[];
  executions?: { id: string; status: string; verified: boolean; result: Record<string, string>; error: string | null }[];
  outcomes?: { id: string; result: string; notes: string; created_at: string }[] }
export interface Task { id: string; title: string; owner_name: string | null; due_date: string | null; status: string; origin: string; decision_id: string | null; source_locator: string | null }
export interface Kpis { open_insights: Record<Severity, number>; commitments_due_soon: number; decisions_awaiting_approval: number; documents_by_status: Record<string, number>; as_of: string }
export interface Deadline { id: string; title: string; customer: string | null; owner: string | null; due_date: string; source_locator: string | null }
export interface Passage { ref: string; document_id: string; filename: string; locator: string; text: string }
export interface AskResult { mode: "ai" | "retrieval_only" | "no_evidence"; answer: string | null; citations: string[]; passages: Passage[]; note?: string; model?: string }
export interface Member { id: string; email: string; display_name: string | null; role: string; status: string; pending: boolean }
export interface AuditEvent { id: number; action: string; actor_user_id: string | null; resource_type: string | null; outcome: string; created_at: string; metadata: Record<string, unknown> }
