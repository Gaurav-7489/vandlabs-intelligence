import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { Badge, Card, Empty, ErrorPanel, PageHeader, SkeletonRows, stateTone, useToast, errorText } from "../components/ui";
import { api, type Doc } from "../lib/api";
import { fmtBytes, fmtDateTime, humanize } from "../lib/format";
import { useCursorList } from "../lib/useCursorList";
import { useOrgKey, useSession } from "../lib/session";

function Uploader() {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useSession();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const m = useMutation({
    mutationFn: (f: File) => { const form = new FormData(); form.append("file", f); return api<Doc>("/documents", { method: "POST", form }); },
    onSuccess: (d) => { toast("ok", d.duplicate ? `“${d.filename}” was already uploaded.` : `“${d.filename}” accepted and queued for processing.`); void qc.invalidateQueries({ predicate: (q) => q.queryKey[1] === "documents" }); },
    onError: (e) => toast("error", errorText(e)),
  });
  if (!can("documents.write")) return null;
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); Array.from(e.dataTransfer.files).forEach((f) => m.mutate(f)); };
  return (
    <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
      className={`card flex flex-col items-center gap-2 border-dashed p-6 text-center transition-colors ${drag ? "border-accent bg-accentsoft" : ""}`}>
      <p className="text-sm">Drop files here, or</p>
      <button className="btn btn-primary" disabled={m.isPending} onClick={() => input.current?.click()}>{m.isPending ? "Uploading…" : "Choose files"}</button>
      <input ref={input} type="file" hidden multiple accept=".pdf,.docx,.csv,.xlsx,.txt" aria-label="Upload documents"
        onChange={(e) => { Array.from(e.target.files ?? []).forEach((f) => m.mutate(f)); e.target.value = ""; }} />
      <p className="text-xs text-ink2">PDF, DOCX, CSV, XLSX, TXT · up to 25 MB · Scanned PDFs need OCR, which is not configured.</p>
    </div>
  );
}

function Documents() {
  const list = useCursorList<Doc>("documents", "/documents", {}, { pollWhile: (docs) => docs.some((d) => d.status === "queued" || d.status === "processing") });
  return (
    <Card title="Documents">
      {list.isPending ? <SkeletonRows /> : list.isError ? <ErrorPanel error={list.error} onRetry={() => void list.refetch()} /> :
        list.items.length === 0 ? <Empty title="No documents yet" hint="Upload a commitments or project-status spreadsheet to see the first insights." /> : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead><tr><th className="th">File</th><th className="th">Status</th><th className="th hidden sm:table-cell">Extracted</th><th className="th hidden md:table-cell">Uploaded</th></tr></thead>
              <tbody className="divide-y divide-line">
                {list.items.map((d) => (
                  <tr key={d.id} className="enter">
                    <td className="td"><p className="font-medium">{d.filename}</p><p className="text-xs text-ink2">{d.type.toUpperCase()} · {fmtBytes(d.size_bytes)}</p></td>
                    <td className="td"><Badge tone={stateTone(d.status)}>{humanize(d.status)}</Badge>{d.error && <p className="mt-1 max-w-xs text-xs text-ink2">{d.error}</p>}</td>
                    <td className="td hidden text-xs text-ink2 sm:table-cell">{typeof d.stats.commitments === "number" ? `${d.stats.commitments} commitments · ${d.stats.tasks} tasks` : "—"}</td>
                    <td className="td hidden text-xs text-ink2 md:table-cell">{fmtDateTime(d.created_at)}</td>
                  </tr>))}
              </tbody>
            </table>
            <div ref={list.sentinel} className="h-px" />
            {list.isFetchingNextPage && <SkeletonRows n={2} />}
          </div>)}
    </Card>
  );
}

function Search() {
  const org = useOrgKey();
  const { can } = useSession();
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const res = useQuery({ queryKey: [org, "search", q], enabled: q.length >= 2, queryFn: ({ signal }) => api<{ items: { chunk_id: string; filename: string; locator: string; text: string }[] }>("/search", { params: { q }, signal }) });
  if (!can("search.read")) return null;
  const submit = (e: FormEvent) => { e.preventDefault(); setQ(term.trim()); };
  return (
    <Card title="Search your knowledge">
      <form onSubmit={submit} className="flex gap-2 p-4" role="search">
        <label className="sr-only" htmlFor="q">Search</label>
        <input id="q" className="input" placeholder="Search documents and records…" value={term} onChange={(e) => setTerm(e.target.value)} maxLength={200} />
        <button className="btn btn-primary">Search</button>
      </form>
      {q.length >= 2 && (res.isPending ? <SkeletonRows n={2} /> : res.isError ? <ErrorPanel error={res.error} onRetry={() => void res.refetch()} /> :
        res.data.items.length === 0 ? <Empty title="No matches" hint="Nothing in the documents you can access matches that search." /> : (
          <ul className="divide-y divide-line border-t border-line">
            {res.data.items.map((r) => (
              <li key={r.chunk_id} className="px-4 py-3 text-sm"><p className="line-clamp-3">{r.text}</p><p className="mt-1 text-xs text-ink2">{r.filename} · {r.locator}</p></li>))}
          </ul>))}
    </Card>
  );
}

export default function Knowledge() {
  return (
    <>
      <PageHeader title="Knowledge" subtitle="Documents are scanned, parsed and indexed in the background. Every record keeps a pointer to its source row or page." />
      <div className="space-y-4"><Uploader /><Search /><Documents /></div>
    </>
  );
}
