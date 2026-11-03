import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Badge, Card, Empty, ErrorPanel, PageHeader, SkeletonRows, sevTone, useToast, errorText } from "../components/ui";
import { api, type Decision, type Insight } from "../lib/api";
import { humanize, fmtDate, fmtDateTime } from "../lib/format";
import { useCursorList } from "../lib/useCursorList";
import { useOrgKey, useSession } from "../lib/session";

function Detail({ ins }: { ins: Insight }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const { can } = useSession();
  const org = useOrgKey();
  const history = useQuery({ queryKey: [org, "insights", "explanations", ins.id], enabled: !!ins.explanation,
    queryFn: ({ signal }) => api<{ items: { id: string; explanation: string; source: string; created_at: string }[] }>(`/insights/${ins.id}/explanations`, { signal }) });
  const refresh = () => qc.invalidateQueries({ predicate: (q) => q.queryKey[1] === "insights" });
  const explain = useMutation({ mutationFn: () => api<Insight>(`/insights/${ins.id}/explain`, { method: "POST" }), onSuccess: () => { toast("ok", "Explanation generated."); void refresh(); }, onError: (e) => toast("error", errorText(e)) });
  const decide = useMutation({ mutationFn: () => api<Decision>("/decisions", { method: "POST", body: { insight_id: ins.id } }), onSuccess: (d) => { toast("ok", "Decision created."); nav(`/decisions/${d.id}`); }, onError: (e) => toast("error", errorText(e)) });
  const setStatus = useMutation({ mutationFn: (status: string) => api(`/insights/${ins.id}`, { method: "PATCH", body: { status } }), onSuccess: () => { toast("ok", "Status updated."); void refresh(); }, onError: (e) => toast("error", errorText(e)) });
  return (
    <div className="enter space-y-4 border-t border-line bg-canvas p-4 text-sm">
      <p>{ins.summary}</p>
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink3">Evidence</h3>
        <ul className="space-y-2">
          {ins.evidence.map((e) => (
            <li key={e.id} className="rounded-lg border border-line bg-surface p-3">
              <p className="font-medium"><Badge>{e.type}</Badge> {String(e.facts.title)}</p>
              <p className="mt-1 text-xs text-ink2">Status {String(e.facts.status)} · due {fmtDate(String(e.facts.due_date))} · owner {String(e.facts.owner ?? "unassigned")} · source <span className="font-mono">{e.locator}</span></p>
            </li>))}
        </ul>
      </div>
      <p><span className="font-medium">Uncertainty: </span>{ins.uncertainty}</p>
      <p><span className="font-medium">Suggested next step: </span>{ins.recommended_step}</p>
      {ins.explanation && (
        <div className="rounded-lg border border-line bg-surface p-3">
          <p className="whitespace-pre-line">{ins.explanation}</p>
          <p className="mt-2 text-xs text-ink2">{ins.explanation_source === "deterministic" ? "Generated from the stored evidence (no AI model used)." : `AI-generated, validated against the evidence above (${ins.explanation_source}).`}</p>
        </div>)}
      {history.data && history.data.items.length > 1 && (
        <details className="rounded-lg border border-line bg-surface p-3"><summary className="cursor-pointer text-xs font-medium text-ink2">Earlier explanations ({history.data.items.length - 1})</summary>
          <ul className="mt-2 space-y-2">{history.data.items.slice(1).map((h) => <li key={h.id} className="text-xs text-ink2"><span className="font-mono">{h.source}</span> · {fmtDateTime(h.created_at)}<p className="mt-1 whitespace-pre-line text-ink">{h.explanation}</p></li>)}</ul></details>)}
      <div className="flex flex-wrap gap-2">
        {can("ai.ask") && <button className="btn" disabled={explain.isPending} onClick={() => explain.mutate()}>{explain.isPending ? "Explaining…" : "Explain"}</button>}
        {can("decisions.write") && <button className="btn btn-primary" disabled={decide.isPending} onClick={() => decide.mutate()}>Create decision</button>}
        {can("insights.write") && ins.status === "open" && <button className="btn" onClick={() => setStatus.mutate("acknowledged")}>Acknowledge</button>}
        {can("insights.write") && ins.status !== "dismissed" && <button className="btn" onClick={() => setStatus.mutate("dismissed")}>Dismiss</button>}
      </div>
    </div>
  );
}

export default function Insights() {
  const [params, setParams] = useSearchParams();
  const severity = params.get("severity") ?? "";
  const status = params.get("status") ?? "open";
  const [openId, setOpenId] = useState<string | null>(null);
  const list = useCursorList<Insight>("insights", "/insights", { severity: severity || undefined, status });
  const set = (k: string, v: string) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); };
  return (
    <>
      <PageHeader title="Insights" subtitle="Risks detected by deterministic rules over your records. Each links back to its evidence." />
      <div className="mb-4 flex flex-wrap gap-3">
        <div><label className="label" htmlFor="sev">Severity</label>
          <select id="sev" className="input" value={severity} onChange={(e) => set("severity", e.target.value)}><option value="">All</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></div>
        <div><label className="label" htmlFor="st">Status</label>
          <select id="st" className="input" value={status} onChange={(e) => set("status", e.target.value)}>{["open", "acknowledged", "resolved", "dismissed"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}</select></div>
      </div>
      <Card>
        {list.isPending ? <SkeletonRows n={5} /> : list.isError ? <ErrorPanel error={list.error} onRetry={() => void list.refetch()} /> :
          list.items.length === 0 ? <Empty title="No insights" hint="When uploaded records show a commitment at risk, it appears here with the evidence behind it." /> : (
            <ul className="divide-y divide-line">
              {list.items.map((i) => (
                <li key={i.id}>
                  <button className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-muted" aria-expanded={openId === i.id} onClick={() => setOpenId(openId === i.id ? null : i.id)}>
                    <Badge tone={sevTone(i.severity)}>{humanize(i.severity)}</Badge>
                    <span className="min-w-0 flex-1"><span className="block truncate font-medium">{i.title}</span><span className="block truncate text-xs text-ink2">{humanize(i.rule)}</span></span>
                  </button>
                  {openId === i.id && <Detail ins={i} />}
                </li>))}
            </ul>)}
        <div ref={list.sentinel} className="h-px" />
        {list.isFetchingNextPage && <SkeletonRows n={2} />}
      </Card>
    </>
  );
}
