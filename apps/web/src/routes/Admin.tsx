import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Badge, Card, Empty, ErrorPanel, PageHeader, SkeletonRows, errorText, useToast } from "../components/ui";
import { api, type AuditEvent, type Member } from "../lib/api";
import { fmtDateTime, humanize } from "../lib/format";
import { useOrgKey, useSession } from "../lib/session";

const ROLES = ["owner", "admin", "manager", "staff", "viewer", "auditor"];

function Members() {
  const org = useOrgKey();
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useSession();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("staff");
  const q = useQuery({ queryKey: [org, "members"], queryFn: ({ signal }) => api<{ items: Member[] }>("/members", { signal }) });
  const refresh = () => qc.invalidateQueries({ queryKey: [org, "members"] });
  const invite = useMutation({ mutationFn: () => api("/members", { method: "POST", body: { email, role } }), onSuccess: () => { toast("ok", "Member added. They can sign in with this email."); setEmail(""); void refresh(); }, onError: (e) => toast("error", errorText(e)) });
  const change = useMutation({ mutationFn: ({ id, role }: { id: string; role: string }) => api(`/members/${id}`, { method: "PATCH", body: { role } }), onSuccess: () => { toast("ok", "Role updated."); void refresh(); }, onError: (e) => toast("error", errorText(e)) });
  const submit = (e: FormEvent) => { e.preventDefault(); invite.mutate(); };
  return (
    <Card title="Members">
      {can("members.write") && (
        <form onSubmit={submit} className="flex flex-wrap items-end gap-2 border-b border-line p-4">
          <div className="min-w-48 flex-1"><label className="label" htmlFor="ie">Email</label><input id="ie" className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div><label className="label" htmlFor="ir">Role</label><select id="ir" className="input" value={role} onChange={(e) => setRole(e.target.value)}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></div>
          <button className="btn btn-primary" disabled={invite.isPending}>Add member</button>
        </form>)}
      {q.isPending ? <SkeletonRows /> : q.isError ? <ErrorPanel error={q.error} onRetry={() => void q.refetch()} /> : (
        <div className="overflow-x-auto"><table className="w-full"><thead><tr><th className="th">Member</th><th className="th">Role</th><th className="th">Status</th></tr></thead>
          <tbody className="divide-y divide-line">{q.data.items.map((m) => (
            <tr key={m.id}><td className="td">{m.email}</td>
              <td className="td">{can("members.write") ? <select className="input w-32" aria-label={`Role for ${m.email}`} value={m.role} onChange={(e) => change.mutate({ id: m.id, role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select> : m.role}</td>
              <td className="td"><Badge tone={m.pending ? "medium" : "ok"}>{m.pending ? "Invited" : humanize(m.status)}</Badge></td></tr>))}</tbody></table></div>)}
    </Card>
  );
}

function Audit() {
  const org = useOrgKey();
  const { can } = useSession();
  const q = useQuery({ queryKey: [org, "audit"], enabled: can("audit.read"), queryFn: ({ signal }) => api<{ items: AuditEvent[] }>("/audit", { params: { limit: 50 }, signal }) });
  if (!can("audit.read")) return <Card title="Audit trail"><Empty title="Restricted" hint="Audit records are visible to owners, administrators and auditors." /></Card>;
  return (
    <Card title="Audit trail">
      {q.isPending ? <SkeletonRows /> : q.isError ? <ErrorPanel error={q.error} onRetry={() => void q.refetch()} /> : q.data.items.length === 0 ? <Empty title="No events yet" /> : (
        <div className="overflow-x-auto"><table className="w-full"><thead><tr><th className="th">When</th><th className="th">Action</th><th className="th">Outcome</th></tr></thead>
          <tbody className="divide-y divide-line">{q.data.items.map((e) => (<tr key={e.id}><td className="td whitespace-nowrap text-xs text-ink2">{fmtDateTime(e.created_at)}</td><td className="td font-mono text-xs">{e.action}</td><td className="td"><Badge tone={e.outcome === "success" ? "ok" : "high"}>{e.outcome}</Badge></td></tr>))}</tbody></table></div>)}
    </Card>
  );
}

export default function Admin() {
  return (<><PageHeader title="Administration" subtitle="Membership, roles and the audit trail for this organization." /><div className="space-y-4"><Members /><Audit /></div></>);
}
