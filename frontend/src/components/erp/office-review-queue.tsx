"use client";

import { useCallback, useEffect, useState } from "react";

type Draft = {
  id: number;
  number: string;
  title: string;
  company: string;
  assignment_revision: number;
  reviewer_subject: string | null;
};
type ReviewQueue = { documents: Draft[]; reviewers: { subject: string; name: string }[] };

export function OfficeReviewQueue() {
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [documentId, setDocumentId] = useState("");
  const [subject, setSubject] = useState("");
  const [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(true);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const draft = queue?.documents.find((row) => String(row.id) === documentId);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await fetch("/api/office/review-queue", { cache: "no-store", signal });
      if (signal?.aborted) return;
      setError("");
      if (response.status === 403) {
        setForbidden(true);
        setQueue(null);
        return;
      }
      if (!response.ok) throw new Error("load");
      const data: ReviewQueue = await response.json();
      if (!Array.isArray(data.documents) || !Array.isArray(data.reviewers)) throw new Error("load");
      if (signal?.aborted) return;
      setQueue(data);
      setDocumentId("");
      setSubject("");
      setEvidence("");
      setNeedsRefresh(false);
      setForbidden(false);
    } catch {
      if (!signal?.aborted) {
        setQueue(null);
        setError("Не удалось загрузить черновики. Обновите список.");
      }
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    // Start after the mount commits; discarded StrictMode mounts send no request.
    queueMicrotask(() => {
      if (!controller.signal.aborted) void load(controller.signal);
    });
    return () => controller.abort();
  }, [load]);

  async function assign(event: React.FormEvent) {
    event.preventDefault();
    if (!draft || !subject || !evidence.trim() || busy || needsRefresh) return;
    setBusy(true);
    setNeedsRefresh(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`/api/office/docs/${draft.id}/shipping-reviewer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject, expected_revision: draft.assignment_revision, evidence: evidence.trim() }),
      });
      if (response.status === 409) {
        setError("Назначение уже изменилось. Обновите список и проверьте текущего проверяющего.");
        return;
      }
      if (!response.ok) {
        setError("Назначение не подтверждено. Обновите список перед следующей попыткой.");
        return;
      }
      const result = await response.json();
      if (result.document_id !== draft.id || result.subject !== subject ||
          result.assignment_revision !== draft.assignment_revision + 1) throw new Error("receipt");
      setNotice("Проверяющий назначен. Сотрудник увидит документ в своей доске.");
      await load();
    } catch {
      setError("Результат назначения неизвестен. Обновите список и проверьте его перед повтором.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Назначение проверяющего" className="w-full overflow-y-auto p-6">
      <h2 className="text-xl font-semibold">Проверяющие черновиков</h2>
      <p className="mt-2 text-sm text-muted">Финансист и помощник создают свои черновики. Руководитель назначает сотрудника, который продолжит работу с документом.</p>
      {forbidden ? <p role="status" className="mt-4">Назначать проверяющего может только руководитель.</p> : <>
        <button type="button" disabled={busy} onClick={() => { setBusy(true); setNotice(""); setError(""); void load(); }} className="my-4 rounded border border-line px-3 py-2 disabled:opacity-50">Обновить список</button>
        {busy && <p role="status">Загрузка…</p>}
        {error && <p role="alert" className="mb-4 text-red-700">{error}</p>}
        {notice && <p role="status" className="mb-4">{notice}</p>}
        {queue && (queue.documents.length === 0 ? <p>Нет черновиков для назначения.</p> : <form onSubmit={assign} className="flex max-w-xl flex-col gap-4">
          <label className="flex flex-col gap-1">Черновик
            <select value={documentId} disabled={busy || needsRefresh} onChange={(event) => { setDocumentId(event.target.value); setSubject(""); }} className="rounded border border-line bg-surface p-2">
              <option value="">Выберите документ</option>
              {queue.documents.map((row) => <option key={row.id} value={row.id}>{row.number} — {row.company || row.title}</option>)}
            </select>
          </label>
          {draft && <p className="text-sm">Текущий проверяющий: {draft.reviewer_subject ? queue.reviewers.find((row) => row.subject === draft.reviewer_subject)?.name ?? "Ранее назначенный сотрудник недоступен" : "не назначен"}.</p>}
          <label className="flex flex-col gap-1">Проверяющий
            <select value={subject} disabled={busy || needsRefresh || !draft} onChange={(event) => setSubject(event.target.value)} className="rounded border border-line bg-surface p-2">
              <option value="">Выберите сотрудника</option>
              {queue.reviewers.map((row) => <option key={row.subject} value={row.subject}>{row.name}</option>)}
            </select>
          </label>
          {queue.reviewers.length === 0 && <p role="status">Нет активных сотрудников с правом работы с офисными документами.</p>}
          <label className="flex flex-col gap-1">Основание назначения
            <textarea value={evidence} maxLength={1000} disabled={busy || needsRefresh} onChange={(event) => setEvidence(event.target.value)} className="rounded border border-line bg-surface p-2" />
          </label>
          <button type="submit" disabled={busy || needsRefresh || !draft || !subject || !evidence.trim()} className="rounded bg-accent px-4 py-2 text-white disabled:opacity-50">Назначить проверяющего</button>
        </form>)}
      </>}
    </section>
  );
}
