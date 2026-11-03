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
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const invite = useMutation({ mutationFn: () => api("/members", { method: "POST", body: { email, role } }),
    onSuccess: () => { toast("ok", "Member added."); setInviteLink(`${window.location.origin}/?invite=1&email=${encodeURIComponent(email)}`); setEmail(""); void refresh(); },
    onError: (e) => toast("error", errorText(e)) });
  const revoke = useMutation({ mutationFn: (id: string) => api<{ revoked: number }>(`/members/${id}/revoke-sessions`, { method: "POST" }),
    onSuccess: (r) => toast("ok", r.revoked ? `Signed out of ${r.revoked} active session(s).` : "No active sessions to end."), onError: (e) => toast("error", errorText(e)) });
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
      {inviteLink && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-accentsoft p-4 text-sm" role="status">
          <span className="text-accent">Share this sign-up link with the invitee (they must verify their email):</span>
          <code className="min-w-0 flex-1 truncate rounded bg-surface px-2 py-1 text-xs">{inviteLink}</code>
          <button className="btn" onClick={() => { void navigator.clipboard?.writeText(inviteLink).then(() => toast("ok", "Link copied.")); }}>Copy</button>
        </div>)}
      {q.isPending ? <SkeletonRows /> : q.isError ? <ErrorPanel error={q.error} onRetry={() => void q.refetch()} /> : (
        <div className="overflow-x-auto"><table className="w-full"><thead><tr><th className="th">Member</th><th className="th">Role</th><th className="th">Status</th>{can("members.write") && <th className="th"><span className="sr-only">Actions</span></th>}</tr></thead>
          <tbody className="divide-y divide-line">{q.data.items.map((m) => (
            <tr key={m.id}><td className="td">{m.email}</td>
              <td className="td">{can("members.write") ? <select className="input w-32" aria-label={`Role for ${m.email}`} value={m.role} onChange={(e) => change.mutate({ id: m.id, role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select> : m.role}</td>
              <td className="td"><Badge tone={m.pending ? "medium" : "ok"}>{m.pending ? "Invited" : humanize(m.status)}</Badge></td>
              {can("members.write") && <td className="td text-right">{!m.pending && <button className="btn" disabled={revoke.isPending} onClick={() => revoke.mutate(m.id)} aria-label={`Sign ${m.email} out everywhere`}>Sign out everywhere</button>}</td>}</tr>))}</tbody></table></div>)}
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
