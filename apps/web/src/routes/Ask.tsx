import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Badge, Card, ErrorPanel, PageHeader, errorText } from "../components/ui";
import { api, type AskResult } from "../lib/api";

export default function Ask() {
  const [q, setQ] = useState("");
  const [history, setHistory] = useState<{ q: string; r: AskResult }[]>([]); // this browser session only; nothing is stored server-side
  const m = useMutation({ mutationFn: (question: string) => api<AskResult>("/intelligence/ask", { method: "POST", body: { question } }),
    onSuccess: (r, question) => setHistory((h) => [{ q: question, r }, ...h].slice(0, 10)) });
  const submit = (e: FormEvent) => { e.preventDefault(); if (q.trim().length >= 3) m.mutate(q.trim()); };
  const r = m.data;
  return (
    <>
      <PageHeader title="Ask Intelligence" subtitle="Answers are drawn only from your documents and cite their sources. If the evidence isn't there, it says so." />
      <form onSubmit={submit} className="card mb-4 flex flex-col gap-2 p-4 sm:flex-row">
        <label htmlFor="ask" className="sr-only">Question</label>
        <input id="ask" className="input" placeholder="e.g. Which commitments depend on the API adapter?" value={q} onChange={(e) => setQ(e.target.value)} maxLength={1000} />
        <button className="btn btn-primary" disabled={m.isPending || q.trim().length < 3}>{m.isPending ? "Thinking…" : "Ask"}</button>
      </form>
      <div aria-live="polite">
        {m.isError && <Card><ErrorPanel error={m.error} onRetry={() => m.mutate(q.trim())} /></Card>}
        {r && (
          <div className="enter space-y-4">
            <Card className="p-4">
              <div className="mb-2 flex items-center gap-2"><Badge tone={r.mode === "ai" ? "accent" : r.mode === "no_evidence" ? "medium" : undefined}>
                {r.mode === "ai" ? `AI answer · ${r.model}` : r.mode === "no_evidence" ? "Insufficient evidence" : "Source passages only"}</Badge></div>
              {r.answer ? <p className="whitespace-pre-line text-sm">{r.answer}</p> : <p className="text-sm text-ink2">{r.note ?? "No answer was generated."}</p>}
              {r.citations.length > 0 && <p className="mt-2 text-xs text-ink2">Cited: {r.citations.join(", ")}</p>}
            </Card>
            {r.passages.length > 0 && (
              <Card title="Sources"><ul className="divide-y divide-line">{r.passages.map((p) => (
                <li key={p.ref} className="px-4 py-3 text-sm"><p><Badge>{p.ref}</Badge> <span className="line-clamp-3">{p.text}</span></p><p className="mt-1 text-xs text-ink2">{p.filename} · {p.locator}</p></li>))}</ul></Card>)}
          </div>)}
      </div>
      {history.length > 1 && (
        <Card title="Earlier in this session" className="mt-4"><ul className="divide-y divide-line">{history.slice(1).map((h, i) => (
          <li key={i} className="px-4 py-3 text-sm"><p className="font-medium">{h.q}</p><p className="line-clamp-2 text-ink2">{h.r.answer ?? h.r.note ?? "No answer"}</p></li>))}</ul></Card>)}
      {m.isError && <p className="sr-only">{errorText(m.error)}</p>}
    </>
  );
}
