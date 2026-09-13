"use client";
import { useState } from "react";

export type ReservationDraft = { source: string; version: number; sku_code: string; warehouse: string; qty: string };
export function WmsReservationEditor({ organizationId, initial, onBusy, onSaved, onCancel }: {
  organizationId: number; initial: ReservationDraft | null; onBusy: (busy: boolean) => void;
  onSaved: () => void; onCancel: () => void;
}) {
  const [source, setSource] = useState(initial?.source ?? "");
  const [sku, setSku] = useState(initial?.sku_code ?? "");
  const [warehouse, setWarehouse] = useState(initial?.warehouse ?? "");
  const [qty, setQty] = useState(initial?.qty ?? "");
  const [evidence, setEvidence] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function save() {
    const amount = qty.trim().replace(",", ".");
    if (!/^\d{1,12}(\.\d{1,2})?$/.test(amount) || (!initial && /^0+(\.0+)?$/.test(amount))) {
      setError("Укажите количество с точностью до двух знаков. Первый резерв должен быть больше нуля."); return;
    }
    if (!source.trim() || !sku.trim() || !warehouse.trim() || !evidence.trim()) {
      setError("Заполните исходную строку, номенклатуру, склад и основание."); return;
    }
    setBusy(true); onBusy(true); setError("");
    try {
      const response = await fetch("/api/wms/reservations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        organization_id: organizationId, source: source.trim(), version: (initial?.version ?? 0) + 1,
        sku_code: sku.trim(), warehouse: warehouse.trim(), qty: amount, evidence: evidence.trim(),
      }) });
      if (response.status === 409) {
        setError("Версия уже существует или данные изменились. Обновите список и сравните историю; введённые значения сохранены."); return;
      }
      if (!response.ok) throw new Error("Save failed");
      onSaved();
    } catch {
      setError("Не удалось подтвердить запись. Ввод сохранён. Повтор с теми же данными не создаёт дубль; перед изменением данных проверьте историю.");
    } finally { setBusy(false); onBusy(false); }
  }
  return <section className="my-4 rounded border border-line p-4">
    <h2 className="font-semibold">{initial ? "Изменение резерва" : "Новый резерв"} · версия {(initial?.version ?? 0) + 1}</h2>
    <p className="my-2 text-sm text-muted">Количество — остаток резерва после изменения. Для полного снятия укажите 0. Укажите устойчивый идентификатор строки исходного документа; автоматического сопоставления с продажами пока нет.</p>
    <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-2">
      <label>Исходная строка<input aria-label="Исходная строка" className="block w-full rounded border border-line bg-surface p-2" disabled={Boolean(initial)} maxLength={200} value={source} onChange={(e) => setSource(e.target.value)} /></label>
      <label>Код номенклатуры<input aria-label="Код номенклатуры" className="block w-full rounded border border-line bg-surface p-2" disabled={Boolean(initial)} maxLength={64} value={sku} onChange={(e) => setSku(e.target.value)} /></label>
      <label>Склад резерва<input aria-label="Склад резерва" className="block w-full rounded border border-line bg-surface p-2" disabled={Boolean(initial)} maxLength={128} value={warehouse} onChange={(e) => setWarehouse(e.target.value)} /></label>
      <label>Количество резерва<input aria-label="Количество резерва" inputMode="decimal" className="block w-full rounded border border-line bg-surface p-2" value={qty} onChange={(e) => setQty(e.target.value)} /></label>
      <label className="sm:col-span-2">Основание изменения<textarea aria-label="Основание изменения" className="block w-full rounded border border-line bg-surface p-2" maxLength={1000} value={evidence} onChange={(e) => setEvidence(e.target.value)} /></label>
      <button type="button" className="rounded border border-line p-2" onClick={save}>Записать версию</button>
      <button type="button" className="rounded border border-line p-2" onClick={onCancel}>Закрыть форму</button>
    </fieldset>
    {error && <p role="alert" className="mt-2 text-sm text-red-600">{error}</p>}
  </section>;
}
