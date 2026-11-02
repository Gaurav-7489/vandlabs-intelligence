import { Badge, Card, PageHeader } from "../components/ui";

const CONNECTORS = [
  { name: "File upload & structured import", status: "Available", note: "PDF, DOCX, CSV, XLSX, TXT via Knowledge.", ok: true },
  { name: "Google Drive (read-only)", status: "Not connected", note: "Connector framework not yet implemented. Requires OAuth client credentials.", ok: false },
  { name: "GitHub (read-only)", status: "Not connected", note: "Connector framework not yet implemented. Requires a GitHub App.", ok: false },
];

export default function Integrations() {
  return (
    <>
      <PageHeader title="Integrations" subtitle="Only real, working sources are marked available. Nothing here is simulated." />
      <Card><ul className="divide-y divide-line">{CONNECTORS.map((c) => (
        <li key={c.name} className="flex flex-wrap items-center justify-between gap-2 px-4 py-4"><div><p className="font-medium">{c.name}</p><p className="text-sm text-ink2">{c.note}</p></div>
          <Badge tone={c.ok ? "ok" : undefined}>{c.status}</Badge></li>))}</ul></Card>
    </>
  );
}
