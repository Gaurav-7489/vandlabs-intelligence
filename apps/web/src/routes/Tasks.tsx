import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Card, Empty, ErrorPanel, PageHeader, SkeletonRows, errorText, stateTone, useToast } from "../components/ui";
import { api, type Task } from "../lib/api";
import { fmtDate, humanize } from "../lib/format";
import { useCursorList } from "../lib/useCursorList";
import { useSession } from "../lib/session";

export default function Tasks() {
  const [params, setParams] = useSearchParams();
  const origin = params.get("origin") ?? "";
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useSession();
  const list = useCursorList<Task>("tasks", "/tasks", { origin: origin || undefined });
  const mut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api(`/tasks/${id}`, { method: "PATCH", body: { status } }),
    onSuccess: () => { toast("ok", "Task updated."); void qc.invalidateQueries({ predicate: (q) => q.queryKey[1] === "tasks" }); },
    onError: (e) => toast("error", errorText(e)),
  });
  const [title, setTitle] = useState("");
  const create = useMutation({ mutationFn: () => api<Task>("/tasks", { method: "POST", body: { title } }),
    onSuccess: () => { toast("ok", "Task created."); setTitle(""); void qc.invalidateQueries({ predicate: (q) => q.queryKey[1] === "tasks" }); },
    onError: (e) => toast("error", errorText(e)) });
  const submit = (e: FormEvent) => { e.preventDefault(); if (title.trim().length >= 3) create.mutate(); };
  return (
    <>
      <PageHeader title="Tasks" subtitle="Imported tasks and follow-ups created by approved decisions." />
      {can("tasks.write") && (
        <form onSubmit={submit} className="card mb-4 flex flex-wrap items-end gap-2 p-4">
          <div className="min-w-48 flex-1"><label className="label" htmlFor="nt">New low-risk task</label>
            <input id="nt" className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={500} placeholder="e.g. Call the client about the delivery date" /></div>
          <button className="btn btn-primary" disabled={create.isPending || title.trim().length < 3}>Add task</button>
          <p className="w-full text-xs text-ink2">Recorded as a direct task in the audit log — not an approved decision. Material actions go through Decisions.</p>
        </form>)}
      <div className="mb-4 max-w-xs"><label className="label" htmlFor="o">Origin</label>
        <select id="o" className="input" value={origin} onChange={(e) => setParams(e.target.value ? { origin: e.target.value } : {}, { replace: true })}>
          <option value="">All</option><option value="imported">Imported from documents</option><option value="execution">Created by decisions</option><option value="direct">Created directly</option></select></div>
      <Card>
        {list.isPending ? <SkeletonRows /> : list.isError ? <ErrorPanel error={list.error} onRetry={() => void list.refetch()} /> :
          list.items.length === 0 ? <Empty title="No tasks" /> : (
            <div className="overflow-x-auto"><table className="w-full">
              <thead><tr><th className="th">Task</th><th className="th">Status</th><th className="th hidden sm:table-cell">Owner</th><th className="th hidden sm:table-cell">Due</th></tr></thead>
              <tbody className="divide-y divide-line">{list.items.map((t) => (
                <tr key={t.id}><td className="td"><p className="font-medium">{t.title}</p><p className="text-xs text-ink2">{t.origin === "execution" ? "Created by decision" : t.origin === "direct" ? "Created directly (not a decision)" : t.source_locator}</p></td>
                  <td className="td">{can("tasks.write") ? (
                    <select className="input w-36" aria-label={`Status of ${t.title}`} value={t.status} onChange={(e) => mut.mutate({ id: t.id, status: e.target.value })}>
                      {["todo", "in_progress", "blocked", "done"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}</select>) : <Badge tone={stateTone(t.status)}>{humanize(t.status)}</Badge>}</td>
                  <td className="td hidden text-ink2 sm:table-cell">{t.owner_name ?? "—"}</td><td className="td hidden text-ink2 sm:table-cell">{fmtDate(t.due_date)}</td></tr>))}</tbody></table></div>)}
        <div ref={list.sentinel} className="h-px" />
      </Card>
    </>
  );
}
