import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, Empty, ErrorPanel, PageHeader, Skeleton, SkeletonRows, Badge, stateTone } from "../components/ui";
import { api, type Deadline, type Decision, type Kpis, type Page } from "../lib/api";
import { fmtDate, humanize } from "../lib/format";
import { useOrgKey, useSession } from "../lib/session";

// Each widget owns its request: they load, fail and retry independently.
function KpiStrip() {
  const org = useOrgKey();
  const q = useQuery({ queryKey: [org, "kpis"], queryFn: ({ signal }) => api<Kpis>("/overview/kpis", { signal }), staleTime: 30_000 });
  if (q.isError) return <Card><ErrorPanel error={q.error} onRetry={() => void q.refetch()} /></Card>;
  const k = q.data;
  const cells: [string, number | undefined, string?][] = [
    ["High-severity risks", k?.open_insights.high, "/insights?severity=high"], ["Medium risks", k?.open_insights.medium, "/insights?severity=medium"],
    ["Commitments due soon", k?.commitments_due_soon], ["Awaiting approval", k?.decisions_awaiting_approval, "/decisions?state=awaiting_approval"],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {cells.map(([label, v, to]) => (
        <div key={label} className="card p-4">
          <p className="text-xs text-ink2">{label}</p>
          {v === undefined ? <Skeleton className="mt-2 h-8 w-12" /> : (
            <p className="mt-1 font-display text-3xl tabular-nums">{to ? <Link to={to} className="hover:text-accent">{v}</Link> : v}</p>)}
        </div>
      ))}
    </div>
  );
}

function Deadlines() {
  const org = useOrgKey();
  const q = useQuery({ queryKey: [org, "deadlines"], queryFn: ({ signal }) => api<{ items: Deadline[] }>("/overview/deadlines", { signal }) });
  return (
    <Card title="Upcoming commitments">
      {q.isPending ? <SkeletonRows /> : q.isError ? <ErrorPanel error={q.error} onRetry={() => void q.refetch()} /> :
        q.data.items.length === 0 ? <Empty title="No commitments yet" hint="Upload a project plan or commitments spreadsheet in Knowledge to get started." /> : (
          <ul className="divide-y divide-line">
            {q.data.items.map((d) => (
              <li key={d.id} className="flex items-start justify-between gap-3 px-4 py-3 text-sm">
                <div className="min-w-0"><p className="truncate font-medium">{d.title}</p><p className="text-xs text-ink2">{d.customer ?? "—"} · {d.owner ?? "Unassigned"} · {d.source_locator}</p></div>
                <time className="shrink-0 text-xs text-ink2" dateTime={d.due_date}>{fmtDate(d.due_date)}</time>
              </li>))}
          </ul>)}
    </Card>
  );
}

function Pending() {
  const org = useOrgKey();
  const q = useQuery({ queryKey: [org, "pending-decisions"], queryFn: ({ signal }) => api<Page<Decision>>("/decisions", { params: { state: "awaiting_approval", limit: 5 }, signal }) });
  return (
    <Card title="Decisions awaiting approval">
      {q.isPending ? <SkeletonRows n={3} /> : q.isError ? <ErrorPanel error={q.error} onRetry={() => void q.refetch()} /> :
        q.data.items.length === 0 ? <Empty title="Nothing waiting" hint="Decisions submitted for approval appear here." /> : (
          <ul className="divide-y divide-line">
            {q.data.items.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                <Link className="truncate font-medium hover:text-accent" to={`/decisions/${d.id}`}>{d.title}</Link><Badge tone={stateTone(d.state)}>{humanize(d.state)}</Badge>
              </li>))}
          </ul>)}
    </Card>
  );
}

export default function Overview() {
  const { membership } = useSession();
  return (
    <>
      <PageHeader title="Overview" subtitle={`${membership?.org_name} — figures below are computed from your uploaded data only.`} />
      <div className="space-y-4">
        <KpiStrip />
        <div className="grid gap-4 lg:grid-cols-2"><Deadlines /><Pending /></div>
      </div>
    </>
  );
}
