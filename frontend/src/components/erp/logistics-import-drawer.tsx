"use client";

import { useState } from "react";

import { GhostButton, Pill } from "@/components/erp/logistics-ui";
import {
  patchImportStage,
  type ImportShipment,
} from "@/lib/logistics-api";
import { IMPORT_FLOW, importStageLabel, nextImportStage } from "@/lib/logistics-domain";
import { formatByn, formatNumber } from "@/lib/format";

// Drawer импортной поставки: цепочка фабрика→консолидация→плечо→таможня→склад,
// кнопка «продвинуть» (ИНФО: PATCH /imports/{id}). При смене на «customs»→«warehouse»
// бэк эмитит logistics.import.customs_cleared + .arrived (наблюдение, не учёт).
// ВАЖНО: остатки и приём на склад здесь НЕ происходят — это wms по procurement.received.

export function ImportDrawer({
  imp,
  onClose,
  onUpdated,
}: {
  imp: ImportShipment;
  onClose: () => void;
  onUpdated: (i: ImportShipment) => void;
}) {
  const [customsText, setCustomsText] = useState(imp.customs_status ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const next = nextImportStage(imp.stage);
  const atEnd = next === imp.stage;

  async function advance(stage: string) {
    setBusy(true);
    setError(null);
    const updated = await patchImportStage(imp.id, { stage });
    setBusy(false);
    if (!updated) {
      setError("Не удалось продвинуть стадию.");
      return;
    }
    onUpdated(updated);
  }

  async function saveCustoms() {
    setBusy(true);
    setError(null);
    const updated = await patchImportStage(imp.id, {
      stage: imp.stage,
      customs_status: customsText || null,
    });
    setBusy(false);
    if (!updated) {
      setError("Не удалось сохранить статус таможни.");
      return;
    }
    onUpdated(updated);
  }

  return (
    <div className="fixed inset-0 z-40 flex">
      <button
        type="button"
        aria-label="Закрыть"
        onClick={onClose}
        className="flex-1 bg-black/30"
      />
      <aside className="relative flex h-full w-full max-w-[520px] flex-col overflow-y-auto border-l border-line bg-surface shadow-pop">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-line bg-surface px-5 py-3">
          <div>
            <div className="text-xs text-muted">{imp.number || `№ ${imp.id}`}</div>
            <h3 className="font-semibold text-ink">
              {imp.flag} {imp.cargo || imp.supplier}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-line bg-surface px-2.5 py-1 text-sm text-muted hover:bg-sunken"
          >
            Закрыть
          </button>
        </header>

        <div className="space-y-4 px-5 py-4">
          <div className="rounded-lg border border-line bg-sunken px-3 py-2 text-xs text-muted">
            Стадии ниже — <span className="font-medium text-ink">ИНФО</span>. Оприходование
            на склад делает «Закупки → Склад» по событию <code>procurement.received</code>;
            логистика лишь отражает движение для дашборда (двойной учёт запрещён).
          </div>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
              {error}
            </div>
          )}

          <section className="grid grid-cols-2 gap-3 text-sm">
            <Field label="Поставщик" value={imp.supplier || "—"} />
            <Field label="Контейнер" value={imp.container_no || "—"} />
            <Field label="Incoterms" value={imp.incoterms || "—"} />
            <Field label="Маршрут" value={imp.route || "—"} />
            <Field label="Количество" value={formatNumber(imp.qty) + " шт"} />
            <Field label="Стоимость" value={formatByn(imp.amount)} />
            <Field label="ETA" value={imp.eta ?? "—"} />
            <Field label="PO" value={imp.po_ref || "—"} />
          </section>

          <section>
            <div className="mb-2 text-xs font-medium text-muted">Цепочка</div>
            <ol className="space-y-1.5">
              {IMPORT_FLOW.map((stage) => {
                const isCurrent = stage === imp.stage;
                const isPast =
                  IMPORT_FLOW.indexOf(stage as (typeof IMPORT_FLOW)[number]) <
                  IMPORT_FLOW.indexOf(imp.stage as (typeof IMPORT_FLOW)[number]);
                const tone = isCurrent
                  ? "text-ink"
                  : isPast
                    ? "text-muted"
                    : "text-faint";
                return (
                  <li key={stage} className={`flex items-center gap-2 text-sm ${tone}`}>
                    <span
                      className={`inline-flex h-4 w-4 items-center justify-center rounded-full border ${
                        isCurrent
                          ? "border-accent bg-accent"
                          : isPast
                            ? "border-emerald-400 bg-emerald-50"
                            : "border-line"
                      }`}
                    />
                    {importStageLabel(stage)}
                    {isCurrent && <Pill text="сейчас" tone="blue" />}
                  </li>
                );
              })}
            </ol>
          </section>

          <section>
            <div className="mb-2 text-xs font-medium text-muted">Действия</div>
            {atEnd ? (
              <p className="text-sm text-muted">Цепочка завершена (приёмка отмечена).</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => advance(next)}
                  disabled={busy}
                  className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
                >
                  → {importStageLabel(next)}
                </button>
              </div>
            )}
          </section>

          {imp.stage === "customs" && (
            <section>
              <div className="mb-2 text-xs font-medium text-muted">Статус оформления (таможня)</div>
              <input
                value={customsText}
                onChange={(e) => setCustomsText(e.target.value)}
                placeholder="напр. «Оформляем, ждём декларацию»"
                className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              />
              <div className="mt-2 flex justify-end">
                <GhostButton onClick={saveCustoms} busy={busy}>
                  Сохранить статус
                </GhostButton>
              </div>
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className="text-ink">{value}</div>
    </div>
  );
}
