"use client";
import { useEffect, useRef, useState } from "react";
import type { DealDoc } from "@/lib/api";
import { fetchRegisterOrganizations, type RegisterOrganization } from "@/lib/document-register-api";
import { allocationError, exact, type Allocation } from "@/lib/invoice-issuance-api";
import { loadReservation, previewReservation, submitReservation, type PendingReservation, type ReservationPreview } from "@/lib/invoice-late-reservation-api";

export function InvoiceLateReservation({ dealId, doc, refresh }: { dealId: string; doc: DealDoc; refresh: () => Promise<void> }) {
  const [orgs, setOrgs] = useState<RegisterOrganization[]>([]);
  const [org, setOrg] = useState("");
  const [preview, setPreview] = useState<ReservationPreview | null>(null);
  const [allocations, setAllocations] = useState<Allocation[]>([]);
  const [pending, setPending] = useState<PendingReservation | null>(null);
  const [evidence, setEvidence] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const lock = useRef(false);
  useEffect(() => {
    let active = true;
    fetchRegisterOrganizations().then(rows => {
      const saved = loadReservation(dealId, doc.id);
      if (saved && !rows.some(r => r.id === saved.command.organization_id)) throw new Error("Нет доступа к юрлицу сохранённого запроса.");
      if (active) { setOrgs(rows); setPending(saved); setOrg(saved ? String(saved.command.organization_id) : ""); setLoaded(true); }
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "Ошибка загрузки"); });
    return () => { active = false; };
  }, [dealId, doc.id]);
  async function run(send: boolean) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      if (!send) {
        setPreview(null); setConfirmed(false);
        const p = await previewReservation(dealId, doc.id, Number(org), doc.version!, doc.content_sha256!);
        setPreview(p); setAllocations(p.lines.map(line => ({ line_no: line.line_no, warehouse: "", qty: line.qty })));
      } else {
        let request = pending;
        if (!request) {
          if (!preview || !confirmed || !evidence.trim()) throw new Error("Подтвердите журнал склада и основание.");
          const problem = allocationError(preview, allocations);
          if (problem) throw new Error(problem);
          const command = { organization_id: preview.organization_id, expected_document_version: preview.document_version,
            expected_content_sha256: preview.content_sha256, request_key: crypto.randomUUID(),
            allocations: allocations.map(a => ({ ...a, qty: exact(a.qty) })), evidence: evidence.trim(), journal_complete: true as const };
          request = { dealId, documentId: doc.id, command, body: JSON.stringify(command) };
          setPending(request);
        }
        await submitReservation(request); setDone(true); setPending(null); await refresh();
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Ошибка запроса"); }
    finally { lock.current = false; setBusy(false); }
  }
  if (done) return <p role="status">Резерв подтверждён. Оригинал счёта сохранён.</p>;
  if (loaded && !pending && doc.reserve_status === "reserved") return <p>Товар зарезервирован.</p>;
  return <details className="mt-2 rounded border border-line p-3">
    <summary>Зарезервировать поступивший товар</summary>
    {error && <p role="alert" className="my-2 text-red-600">{error}</p>}
    {pending ? <><p>Сохранён запрос резерва для юрлица #{pending.command.organization_id}. Повтор сохраняет исходное распределение.</p>
      <button disabled={!loaded || busy} onClick={() => void run(true)}>Повторить исходный запрос резерва</button></> : <fieldset disabled={!loaded || busy}>
      <label>Юрлицо<select className="m-2 rounded border p-2" value={org} onChange={e => { setOrg(e.target.value); setPreview(null); setConfirmed(false); }}>
        <option value="">Выберите юрлицо</option>{orgs.map(o => <option key={o.id} value={o.id}>{o.name} · {o.unp}</option>)}</select></label>
      <button disabled={!org || !doc.version || !doc.content_sha256} onClick={() => void run(false)}>Проверить доступность</button>
      {preview && <><p>Резерв по строкам оригинала счёта. Физическая отгрузка оформляется отдельно.</p>
        {preview.lines.map(line => <p key={line.line_no}>{line.line_no}. {line.name} · {line.sku_code} · {line.qty} {line.unit}</p>)}
        {allocations.map((a, index) => <div className="my-2 flex gap-2" key={index}>
          <span>Строка {a.line_no}</span><select aria-label={`Склад распределения ${index + 1}`} value={a.warehouse} onChange={e => setAllocations(rows => rows.map((r, i) => i === index ? { ...r, warehouse: e.target.value } : r))}>
            <option value="">Выберите склад</option>{preview.availability.rows.filter(r => r.sku_code === preview.lines.find(l => l.line_no === a.line_no)?.sku_code).map(r => <option key={r.warehouse} value={r.warehouse} disabled={r.free === null || r.physical === null}>{r.warehouse} · свободно {r.free ?? "неизвестно"}</option>)}</select>
          <input aria-label={`Количество распределения ${index + 1}`} value={a.qty} onChange={e => setAllocations(rows => rows.map((r, i) => i === index ? { ...r, qty: e.target.value } : r))} />
          <button onClick={() => setAllocations(rows => rows.filter((_, i) => i !== index))}>Убрать</button>
        </div>)}
        {preview.lines.map(line => <button key={line.line_no} className="mr-3 underline" onClick={() => setAllocations(rows => [...rows, { line_no: line.line_no, warehouse: "", qty: "" }])}>Добавить склад для строки {line.line_no}</button>)}
        <label className="block my-2">Основание проверки склада<input className="ml-2 border p-2" maxLength={1000} value={evidence} onChange={e => setEvidence(e.target.value)} /></label>
        <label className="block my-2"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> Подтверждаю полноту журнала склада</label>
        <button disabled={!confirmed || !evidence.trim() || !!allocationError(preview, allocations)} onClick={() => void run(true)}>Подтвердить резерв</button>
      </>}
    </fieldset>}
  </details>;
}
