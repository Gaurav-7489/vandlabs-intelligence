import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Badge, Card, Empty, ErrorPanel, PageHeader, SkeletonRows, errorText, stateTone, useToast } from "../components/ui";
import { api, type Decision } from "../lib/api";
import { fmtDateTime, humanize } from "../lib/format";
import { useCursorList } from "../lib/useCursorList";
import { useOrgKey, useSession } from "../lib/session";

const DONE: Record<string, string> = { submit: "Submitted for approval.", approve: "Decision approved.", reject: "Decision rejected.", defer: "Decision deferred.",
  execute: "Action executed and verified.", outcome: "Outcome recorded.", close: "Decision closed.", reopen: "Decision reopened." };

export function DecisionList() {
  const [params, setParams] = useSearchParams();
  const state = params.get("state") ?? "";
  const list = useCursorList<Decision>("decisions", "/decisions", { state: state || undefined });
  const states = ["recommendation_ready", "awaiting_approval", "approved", "completed", "outcome_measured", "closed", "rejected", "deferred"];
  return (
    <>
      <PageHeader title="Decisions" subtitle="Every decision keeps its evidence, approvals, execution result and measured outcome." />
      <div className="mb-4 max-w-xs"><label className="label" htmlFor="ds">State</label>
        <select id="ds" className="input" value={state} onChange={(e) => setParams(e.target.value ? { state: e.target.value } : {}, { replace: true })}>
          <option value="">All</option>{states.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}</select></div>
      <Card>
        {list.isPending ? <SkeletonRows /> : list.isError ? <ErrorPanel error={list.error} onRetry={() => void list.refetch()} /> :
          list.items.length === 0 ? <Empty title="No decisions" hint="Create one from an insight." /> : (
            <ul className="divide-y divide-line">
              {list.items.map((d) => (
                <li key={d.id}><Link to={`/decisions/${d.id}`} className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-muted">
                  <span className="min-w-0"><span className="block truncate font-medium">{d.title}</span><span className="text-xs text-ink2">{fmtDateTime(d.created_at)}</span></span>
                  <Badge tone={stateTone(d.state)}>{humanize(d.state)}</Badge></Link></li>))}
            </ul>)}
        <div ref={list.sentinel} className="h-px" />
      </Card>
    </>
  );
}

export function DecisionDetail() {
  const { id } = useParams();
  const org = useOrgKey();
  const qc = useQueryClient();
  const toast = useToast();
  const { can, me } = useSession();
  const [comment, setComment] = useState("");
  const [result, setResult] = useState("improved");
  const [notes, setNotes] = useState("");
  const q = useQuery({ queryKey: [org, "decision", id], queryFn: ({ signal }) => api<Decision>(`/decisions/${id}`, { signal }) });
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api<{ execution?: { status: string; verified: boolean; error: string | null } }>(`/decisions/${id}/${path}`, { method: "POST", body }),
    onSuccess: (d, v) => {
      void qc.invalidateQueries({ queryKey: [org] }); setComment("");
      // Only claim success once the server confirms it. A failed execution returns HTTP 200 with status "failed".
      if (v.path === "execute" && !(d.execution?.status === "succeeded" && d.execution.verified)) toast("error", `Execution failed: ${d.execution?.error ?? "not verified"}. The decision is back in Approved.`);
      else toast("ok", DONE[v.path] ?? "Done.");
    },
    onError: (e) => toast("error", errorText(e)),
  });
  if (q.isPending) return <SkeletonRows n={8} />;
  if (q.isError) return <ErrorPanel error={q.error} onRetry={() => void q.refetch()} />;
  const d = q.data;
  const mine = d.requested_by === me?.user.id;
  const run = (path: string, body?: unknown) => act.mutate({ path, body });
  return (
    <div className="space-y-4">
      <PageHeader title={d.title} subtitle={d.business_question} actions={<Badge tone={stateTone(d.state)}>{humanize(d.state)}</Badge>} />
      <Card title="Observation"><div className="space-y-3 p-4 text-sm"><p>{d.observation}</p>
        <ul className="space-y-1.5">{d.evidence.map((e) => <li key={e.id} className="text-xs text-ink2"><Badge>{e.type}</Badge> {String(e.facts.title)} — <span className="font-mono">{e.locator}</span></li>)}</ul></div></Card>
      <Card title="Alternatives & recommendation"><div className="space-y-2 p-4 text-sm">
        {d.alternatives.map((a) => <p key={a.option}><span className="font-medium">{a.option}.</span> <span className="text-ink2">{a.note}</span></p>)}
        <p className="rounded-lg bg-accentsoft p-3 text-accent">Proposed action: {humanize(d.recommended_action.type)} — “{d.recommended_action.title}”</p>
        <p><span className="font-medium">Risks / uncertainty: </span>{d.risks}</p><p><span className="font-medium">Success criteria: </span>{d.success_criteria}</p></div></Card>

      <Card title="What happens next">
        <ol className="list-decimal space-y-1 p-4 pl-8 text-sm text-ink2">
          <li className={d.state === "recommendation_ready" ? "font-medium text-ink" : ""}>The requester submits the decision for approval.</li>
          <li className={d.state === "awaiting_approval" ? "font-medium text-ink" : ""}>A different person with approval authority approves, rejects or defers it. The requester cannot approve their own decision.</li>
          <li className={d.state === "approved" ? "font-medium text-ink" : ""}>An authorized user executes the approved action: “{d.recommended_action.title}”. Nothing runs before approval.</li>
          <li className={d.state === "completed" ? "font-medium text-ink" : ""}>The system verifies the result by re-reading the created record, then someone records the real-world outcome.</li>
        </ol>
        <p className="border-t border-line px-4 py-3 text-xs text-ink2">Requested by {mine ? "you" : "a colleague"} · {d.approver_user_id ? "decided by an approver" : "no approver yet"}.</p>
      </Card>
      <Card title="Actions"><div className="space-y-3 p-4">
        {d.state === "recommendation_ready" && can("decisions.write") && <button className="btn btn-primary" disabled={act.isPending} onClick={() => run("submit")}>Submit for approval</button>}
        {d.state === "awaiting_approval" && can("decisions.approve") && (mine
          ? <p className="text-sm text-ink2">You proposed this decision, so someone else must approve it.</p>
          : <div className="space-y-2"><label className="label" htmlFor="c">Comment (optional)</label><input id="c" className="input" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
            <div className="flex flex-wrap gap-2"><button className="btn btn-primary" disabled={act.isPending} onClick={() => run("approve", { comment })}>Approve</button>
              <button className="btn" disabled={act.isPending} onClick={() => run("defer", { comment })}>Defer</button>
              <button className="btn btn-danger" disabled={act.isPending} onClick={() => run("reject", { comment })}>Reject</button></div></div>)}
        {d.state === "approved" && can("decisions.execute") && <button className="btn btn-primary" disabled={act.isPending} onClick={() => run("execute")}>{act.isPending ? "Executing…" : "Execute approved action"}</button>}
        {d.state === "completed" && can("decisions.write") && (
          <div className="space-y-2"><div className="grid gap-2 sm:grid-cols-[160px_1fr]"><div><label className="label" htmlFor="r">Outcome</label>
            <select id="r" className="input" value={result} onChange={(e) => setResult(e.target.value)}>{["improved", "unchanged", "worse", "unknown"].map((r) => <option key={r}>{r}</option>)}</select></div>
            <div><label className="label" htmlFor="n">Notes</label><input id="n" className="input" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={4000} /></div></div>
            <button className="btn btn-primary" disabled={act.isPending} onClick={() => run("outcome", { result, notes })}>Record outcome</button></div>)}
        {d.state === "outcome_measured" && can("decisions.write") && <button className="btn" onClick={() => run("close")}>Close decision</button>}
        {["rejected", "deferred", "closed"].includes(d.state) && can("decisions.write") && <button className="btn" onClick={() => run("reopen")}>Reopen</button>}
        {!["recommendation_ready", "awaiting_approval", "approved", "completed", "outcome_measured", "rejected", "deferred", "closed"].includes(d.state) && <p className="text-sm text-ink2">No actions available.</p>}
      </div></Card>

      <Card title="History"><ul className="divide-y divide-line text-sm">
        {(d.approvals ?? []).map((a) => <li key={a.id} className="px-4 py-3"><Badge tone={a.action === "approve" ? "ok" : "medium"}>{humanize(a.action)}</Badge> <span className="text-ink2">{fmtDateTime(a.created_at)}</span>{a.comment && <p className="mt-1">{a.comment}</p>}</li>)}
        {(d.executions ?? []).map((e) => <li key={e.id} className="px-4 py-3"><Badge tone={stateTone(e.status)}>Execution {e.status}</Badge> {e.verified && <Badge tone="ok">Verified</Badge>} {e.result.task_id && <Link className="ml-2 text-accent underline" to="/tasks?origin=execution">View task</Link>}{e.error && <p className="mt-1 text-danger">{e.error}</p>}</li>)}
        {(d.outcomes ?? []).map((o) => <li key={o.id} className="px-4 py-3"><Badge tone={o.result === "improved" ? "ok" : "medium"}>Outcome: {o.result}</Badge> <span className="text-ink2">{fmtDateTime(o.created_at)}</span>{o.notes && <p className="mt-1">{o.notes}</p>}</li>)}
        {!(d.approvals?.length || d.executions?.length || d.outcomes?.length) && <li className="px-4 py-6 text-center text-ink2">No history yet.</li>}
      </ul></Card>
    </div>
  );
}
