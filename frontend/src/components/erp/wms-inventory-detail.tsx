"use client";

import clsx from "clsx";
import { CheckCircle2, Download, Lock } from "lucide-react";
import { useRef, useState } from "react";
import Link from "next/link";
import { useInventoryRequestScope } from "./wms-inventory-source";

import { formatByn, formatNumber } from "@/lib/format";
import {
  completeInventory,
  InventoryRequestError,
  fetchInventoryDetail,
  type InventoryDetail,
  inventoryStatusLabel,
  populateInventory,
  updateInventoryLine,
  varianceTone,
} from "@/lib/wms-inventory";

const TONE_STYLES: Record<string, string> = {
  none: "text-faint",
  ok: "text-green-600",
  short: "text-red-600 font-semibold",
  over: "text-amber-600 font-semibold",
};

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className={clsx("mt-1 text-xl font-bold tabular-nums", tone ?? "text-ink")}>{value}</div>
    </div>
  );
}

export function WmsInventoryDetail({ initial }: { initial: InventoryDetail }) {
  return <InventoryDetailBody key={JSON.stringify(initial)} initial={initial} />;
}

function InventoryDetailBody({ initial }: { initial: InventoryDetail }) {
  const [doc, setDoc] = useState<InventoryDetail>(initial);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [needsRecount, setNeedsRecount] = useState(false);
  const action = useRef(false);
  const request = useInventoryRequestScope();
  const busy = request.busy;
  const locked = doc.status !== "open" || doc.organization_id === null || doc.expected_source !== "wms_physical";
  const canComplete = !locked && !needsRecount && Boolean(doc.snapshot_version) && doc.lines.length > 0
    && doc.lines.every((line) => line.counted_qty !== null) && Object.keys(drafts).length === 0;

  async function refresh() {
    if (action.current) return;
    action.current = true;
    const ticket = request.begin();
    try { const fresh = await fetchInventoryDetail(doc.id); if (request.current(ticket)) setDoc(fresh); }
    catch (error) { request.fail(ticket, error); }
    finally { action.current = false; request.finish(ticket); }
  }

  async function onPopulate() {
    if (action.current || locked || needsRecount) return;
    action.current = true;
    const ticket = request.begin();
    try { const fresh = await populateInventory(doc.id); if (request.current(ticket)) setDoc(fresh); }
    catch (error) {
      request.fail(ticket, error);
      if (request.current(ticket) && doc.snapshot_version && error instanceof InventoryRequestError && error.status === 409) setNeedsRecount(true);
    } finally { action.current = false; request.finish(ticket); }
  }

  async function onComplete() {
    if (action.current || !canComplete) return;
    action.current = true;
    const ticket = request.begin();
    try {
      const completed = await completeInventory(doc.id);
      if (request.current(ticket)) setDoc((value) => ({ ...value, ...completed }));
    } catch (error) {
      request.fail(ticket, error);
      if (request.current(ticket) && error instanceof InventoryRequestError && error.status === 409) setNeedsRecount(true);
    } finally { action.current = false; request.finish(ticket); }
  }

  async function commitCount(lineId: number) {
    const raw = drafts[lineId];
    if (raw === undefined || action.current || locked) return;
    const value = Number(raw.replace(",", "."));
    if (!/^\d+(?:[.,]\d{1,2})?$/.test(raw.trim()) || !Number.isFinite(value) || value < 0 || value >= 1e12) {
      request.setError("Введите неотрицательное количество с точностью до двух знаков. Пустое значение не считается нулём."); return;
    }
    action.current = true;
    const ticket = request.begin();
    try {
      await updateInventoryLine(lineId, { counted_qty: value });
      if (!request.current(ticket)) return;
      const fresh = await fetchInventoryDetail(doc.id);
      if (request.current(ticket)) {
        setDoc(fresh);
        setDrafts((value) => { const next = { ...value }; delete next[lineId]; return next; });
      }
    } catch (error) { request.fail(ticket, error); }
    finally { action.current = false; request.finish(ticket); }
  }

  const s = doc.summary;

  return (
    <div className="min-w-0 flex-1 overflow-auto p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold text-ink">{doc.number}</h1>
            <span
              className={clsx(
                "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
                locked ? "bg-green-50 text-green-600" : "bg-amber-50 text-amber-600",
              )}
            >
              {locked && <Lock size={11} />}
              {inventoryStatusLabel(doc.status)}
            </span>
          </div>
          <p className="mt-0.5 text-sm text-muted">Склад: {doc.warehouse}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!locked && (
            <button
              onClick={onPopulate}
              disabled={busy || needsRecount}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
            >
              <Download size={15} /> Зафиксировать снимок WMS
            </button>
          )}
          {!locked && doc.lines.length > 0 && (
            <button
              onClick={onComplete}
              disabled={busy || !canComplete}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
            >
              <CheckCircle2 size={15} /> Провести
            </button>
          )}
        </div>
      </div>

      {request.error && <div role="alert" className="mt-3 text-sm text-red-600">{request.error}</div>}
      {busy && <p role="status" className="mt-3 text-sm">Выполняется запрос…</p>}
      <button onClick={refresh} disabled={busy} className="mt-3 text-sm underline">Обновить документ</button>
      {needsRecount && <p className="mt-3 text-sm"><Link className="text-accent-ink underline" href={`/erp/wms/inventory?organization_id=${doc.organization_id}`}>Создать новый пересчёт</Link>. Исходный снимок не перезаписывается.</p>}
      <dl className="mt-4 space-y-1 rounded-xl border border-line p-4 text-sm">
        <div><dt className="inline font-medium">Юрлицо: </dt><dd className="inline">{doc.organization_id ?? "Не подтверждено"}</dd></div>
        <div><dt className="inline font-medium">Источник: </dt><dd className="inline">{doc.expected_source === "wms_physical" ? "Физический журнал WMS" : "Не подтверждён"}</dd></div>
        <div><dt className="inline font-medium">Основание: </dt><dd className="inline">{doc.source_evidence || "Неизвестно"}</dd></div>
        <div><dt className="inline font-medium">Полноту подтвердил: </dt><dd className="inline">{doc.journal_confirmed_by || "Неизвестно"} · {doc.journal_confirmed_at || "Время неизвестно"}</dd></div>
        <div><dt className="inline font-medium">Версия снимка: </dt><dd className="inline break-all font-mono text-xs">{doc.snapshot_version || "Не зафиксирована"}</dd></div>
        <div><dt className="inline font-medium">Последнее движение снимка: </dt><dd className="inline">{doc.snapshot_cutoff ?? "Неизвестно"}</dd></div>
        <div><dt className="inline font-medium">Время снимка: </dt><dd className="inline">{doc.snapshot_at || "Не зафиксировано"}</dd></div>
      </dl>
      <p className="mt-2 text-sm text-muted">Ожидаемое относится к физическому журналу этого юрлица и склада. Без подтверждённой себестоимости денежная оценка неизвестна.</p>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Строк / посчитано" value={`${s.counted} / ${s.lines}`} />
        <Kpi label="Недостач" value={formatNumber(s.shortages)} tone={s.shortages ? "text-red-600" : undefined} />
        <Kpi label="Стоимость недостач" value={s.shortage_value === null ? "Неизвестно" : formatByn(s.shortage_value)} tone={s.shortage_value ? "text-red-600" : undefined} />
        <Kpi label="Стоимость излишков" value={s.surplus_value === null ? "Неизвестно" : formatByn(s.surplus_value)} tone={s.surplus_value ? "text-amber-600" : undefined} />
      </div>

      {doc.status === "done" && (
        <div className="mt-4 rounded-xl border border-line bg-sunken px-4 py-3 text-sm text-muted">
          Инвентаризация проведена{doc.completed_at ? ` ${new Date(doc.completed_at).toLocaleString("ru-RU")}` : ""}.
          Корректировки записаны в физический журнал указанного юрлица. Сверка с 1С этим не подтверждается.
        </div>
      )}

      <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Код</th>
              <th className="px-4 py-2 font-medium">Номенклатура</th>
              <th className="px-4 py-2 text-right font-medium">Ожидается (WMS)</th>
              <th className="px-4 py-2 text-right font-medium">Факт</th>
              <th className="px-4 py-2 text-right font-medium">Расхождение</th>
              <th className="px-4 py-2 text-right font-medium">В деньгах</th>
            </tr>
          </thead>
          <tbody>
            {doc.lines.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted">
                  Снимок ещё не заполнен. Зафиксируйте физический журнал выбранного юрлица; отсутствие данных не означает нулевой остаток.
                </td>
              </tr>
            )}
            {doc.lines.map((l) => {
              const tone = varianceTone(l.variance);
              return (
                <tr key={l.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{l.sku_code}</td>
                  <td className="px-4 py-2.5 text-ink">{l.sku_title || "—"}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                    {formatNumber(l.expected_qty)} <span className="text-faint">{l.unit}</span>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {locked ? (
                      <span className="tabular-nums text-ink">
                        {l.counted_qty === null ? "—" : formatNumber(l.counted_qty)}
                      </span>
                    ) : (
                      <input
                        aria-label={`Факт ${l.sku_code}`}
                        disabled={busy || needsRecount}
                        value={drafts[l.id] ?? (l.counted_qty === null ? "" : String(l.counted_qty))}
                        onChange={(e) => setDrafts((d) => ({ ...d, [l.id]: e.target.value }))}
                        onBlur={() => commitCount(l.id)}
                        onKeyDown={(e) => e.key === "Enter" && commitCount(l.id)}
                        inputMode="decimal"
                        placeholder="—"
                        className="w-20 rounded-lg border border-line bg-surface px-2 py-1 text-right text-sm tabular-nums text-ink outline-none focus:border-accent"
                      />
                    )}
                  </td>
                  <td className={clsx("px-4 py-2.5 text-right tabular-nums", TONE_STYLES[tone])}>
                    {l.variance === null ? "—" : l.variance > 0 ? `+${formatNumber(l.variance)}` : formatNumber(l.variance)}
                  </td>
                  <td className={clsx("px-4 py-2.5 text-right tabular-nums", TONE_STYLES[tone])}>
                    {l.variance_value === null ? "Неизвестно" : formatByn(l.variance_value)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
