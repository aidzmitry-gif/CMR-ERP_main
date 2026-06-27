"use client";

import { useMemo, useState } from "react";

import {
  bulkUpsertRef,
  parseRefCsv,
  type BulkApplied,
  type BulkPlan,
  type BulkResult,
} from "@/lib/reference-data";

// Импортируемые справочники-классификаторы (НЕ контрагенты — те в отдельном табе/Синк).
// cols — порядок колонок CSV; первая — natural key (code).
const IMPORT_REFS: { table: string; label: string; cols: string[] }[] = [
  { table: "units", label: "Единицы измерения", cols: ["code", "title"] },
  { table: "currencies", label: "Валюты", cols: ["code", "title"] },
  { table: "countries", label: "Страны", cols: ["code", "title"] },
  { table: "banks", label: "Банки", cols: ["code", "title", "swift"] },
  { table: "accounts", label: "План счетов", cols: ["code", "title", "kind", "parent_id"] },
  { table: "regions", label: "Регионы и города", cols: ["code", "title", "kind", "parent_id"] },
  { table: "nomenclature-groups", label: "Группы номенклатуры", cols: ["code", "name", "parent_id"] },
];

function isPlan(r: BulkResult): r is BulkPlan {
  return (r as BulkPlan).dry_run === true;
}

export function SpravImportRefs() {
  const [table, setTable] = useState(IMPORT_REFS[0].table);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<BulkPlan | null>(null);
  const [applied, setApplied] = useState<BulkApplied | null>(null);

  const cfg = useMemo(() => IMPORT_REFS.find((r) => r.table === table)!, [table]);
  const rows = useMemo(() => parseRefCsv(text, cfg.cols), [text, cfg]);

  function reset() {
    setPlan(null);
    setApplied(null);
    setError(null);
  }

  async function run(dryRun: boolean) {
    if (rows.length === 0) {
      setError("Нет строк для импорта — вставьте данные.");
      return;
    }
    setBusy(dryRun ? "preview" : "apply");
    setError(null);
    setApplied(null);
    const res = await bulkUpsertRef(table, rows, dryRun);
    setBusy(null);
    if (res === null) {
      setError("Ошибка запроса (нет доступа или бэкенд недоступен).");
      return;
    }
    if (isPlan(res)) {
      setPlan(res);
    } else {
      setApplied(res);
      setPlan(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-accent-soft/60 px-4 py-2.5 text-[12px] text-muted">
        <span className="font-semibold text-accent-ink">Импорт классификаторов.</span>{" "}
        Вставьте таблицу (CSV/из Excel), сверьте план (dry-run), затем примените. Идемпотентно —
        повтор не плодит дубли. Контрагенты импортируются в отдельном табе (через 1С/Синк).
      </div>

      {/* Выбор справочника + формат */}
      <div className="rounded-2xl bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-muted">Справочник</label>
            <select
              value={table}
              onChange={(e) => {
                setTable(e.target.value);
                reset();
              }}
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
            >
              {IMPORT_REFS.map((r) => (
                <option key={r.table} value={r.table}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
          <p className="text-[12px] text-faint">
            Колонки по порядку:{" "}
            <span className="font-mono text-muted">{cfg.cols.join(" · ")}</span>
          </p>
        </div>

        <textarea
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            reset();
          }}
          rows={6}
          placeholder={`${cfg.cols.join(",")}\n${cfg.cols.map((c) => `<${c}>`).join(",")}`}
          className="mt-3 w-full rounded-xl border border-line bg-surface px-3 py-2 font-mono text-[13px] text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
        />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-[12px] text-muted">Распознано строк: {rows.length}</span>
          <div className="flex-1" />
          <button
            onClick={() => void run(true)}
            disabled={busy !== null || rows.length === 0}
            className="rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line disabled:opacity-50"
          >
            {busy === "preview" ? "Проверка…" : "Предпросмотр (dry-run)"}
          </button>
          <button
            onClick={() => void run(false)}
            disabled={busy !== null || !plan}
            title={!plan ? "Сначала сделайте предпросмотр" : ""}
            className="rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card disabled:opacity-50"
          >
            {busy === "apply" ? "Применение…" : "Применить"}
          </button>
        </div>

        {/* ОШИБКА */}
        {error && (
          <div className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">
            {error}
          </div>
        )}
      </div>

      {/* ПЛАН (dry-run) — конфликты показываем явно ПЕРЕД записью */}
      {plan && (
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-faint">
              План (dry-run)
            </span>
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
              создать {plan.would_create.length}
            </span>
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
              обновить {plan.would_update.length}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-[11px] ${
                plan.conflicts.length > 0 ? "bg-rose-50 text-rose-700" : "bg-sunken text-muted"
              }`}
            >
              конфликтов {plan.conflicts.length}
            </span>
          </div>

          {plan.conflicts.length > 0 && (
            <div className="mt-3 rounded-xl bg-rose-50/60 p-3 ring-1 ring-rose-200">
              <p className="text-[12px] font-semibold text-rose-700">
                Конфликтные строки в импорт не попадут:
              </p>
              <ul className="mt-1 space-y-0.5 text-[12px] text-rose-700">
                {plan.conflicts.map((c, i) => (
                  <li key={i}>
                    <span className="font-mono">{c.key ?? "—"}</span>: {c.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {plan.would_update.length > 0 && (
            <div className="mt-3">
              <p className="text-[12px] text-muted">Будут обновлены:</p>
              <ul className="mt-1 space-y-0.5 text-[12px]">
                {plan.would_update.map((u) => (
                  <li key={u.key} className="font-mono text-ink">
                    {u.key}{" "}
                    <span className="text-faint">
                      ({Object.keys(u.changes).join(", ")})
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {plan.would_create.length === 0 &&
            plan.would_update.length === 0 &&
            plan.conflicts.length === 0 && (
              <p className="mt-3 text-[12px] text-faint">
                Изменений нет — данные уже актуальны (идемпотентность).
              </p>
            )}
        </div>
      )}

      {/* УСПЕХ (после применения) */}
      {applied && (
        <div className="rounded-2xl bg-emerald-50 p-4 text-emerald-800 ring-1 ring-emerald-200">
          Импортировано: создано <b>{applied.created}</b>, обновлено <b>{applied.updated}</b>
          {applied.conflicts.length > 0 && <>, пропущено конфликтов <b>{applied.conflicts.length}</b></>}.
        </div>
      )}
    </div>
  );
}
