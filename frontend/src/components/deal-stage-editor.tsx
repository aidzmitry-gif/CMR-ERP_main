"use client";

import { useCallback, useEffect, useState } from "react";
import { createStage, deleteStage, type StageRow, updateStage } from "@/lib/api";

/**
 * Редактор стадий воронки (Сделки 2.0): CRUD справочника sales.stage — имя, порядок,
 * вероятность (0..100), тип (обычная/успех/условный отказ/отказ), цвет, активность.
 *
 * Реальный бэк /sales/stages (первый GET лениво материализует канон). Доска читает стадии
 * отсюда. Состояния: загрузка / ошибка+повтор / honest-empty / данные. Удаление стадии со
 * сделками → 409 (бэк не даёт осиротить Deal.stage) — показываем причину.
 */
const KINDS: { id: StageRow["kind"]; label: string }[] = [
  { id: "normal", label: "Обычная" },
  { id: "won", label: "Успех" },
  { id: "cond_lost", label: "Условный отказ" },
  { id: "lost", label: "Отказ" },
];

type Status = "loading" | "error" | "ready";

const EMPTY_NEW: StageRow = {
  code: "",
  title: "",
  sort_order: 0,
  probability: 0,
  kind: "normal",
  color: "#64748B",
  is_active: true,
};

export function DealStageEditor() {
  const [status, setStatus] = useState<Status>("loading");
  const [rows, setRows] = useState<StageRow[]>([]);
  const [draft, setDraft] = useState<StageRow>(EMPTY_NEW);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const res = await fetch("/api/sales/stages", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      setRows((await res.json()) as StageRow[]);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function patchRow(code: string, patch: Partial<StageRow>) {
    setRows((rs) => rs.map((r) => (r.code === code ? { ...r, ...patch } : r)));
  }

  async function save(row: StageRow) {
    setBusy(true);
    setNotice(null);
    const ok = await updateStage(row.code, {
      title: row.title,
      sort_order: row.sort_order,
      probability: row.probability,
      kind: row.kind,
      color: row.color,
      is_active: row.is_active,
    });
    setNotice(ok ? `Сохранено: ${row.title}` : `Не удалось сохранить ${row.title}`);
    setBusy(false);
    if (ok) await load();
  }

  async function remove(row: StageRow) {
    setBusy(true);
    setNotice(null);
    const res = await deleteStage(row.code);
    setNotice(res.ok ? `Удалена: ${row.title}` : res.detail ?? `Не удалось удалить ${row.title}`);
    setBusy(false);
    if (res.ok) await load();
  }

  async function add() {
    if (!draft.code.trim() || !draft.title.trim()) {
      setNotice("Заполните код и название новой стадии");
      return;
    }
    setBusy(true);
    setNotice(null);
    const ok = await createStage(draft);
    setNotice(ok ? `Добавлена: ${draft.title}` : "Не удалось добавить (код занят?)");
    setBusy(false);
    if (ok) {
      setDraft(EMPTY_NEW);
      await load();
    }
  }

  if (status === "loading") {
    return <div className="rounded-xl border border-line bg-sunken p-6 text-sm text-muted">Загрузка стадий…</div>;
  }
  if (status === "error") {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
        <span className="text-sm text-muted">Не удалось загрузить стадии.</span>
        <button onClick={() => void load()} className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white">
          Повторить
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {notice && (
        <div className="rounded-lg border border-line bg-sunken px-3 py-2 text-[12.5px] text-ink">{notice}</div>
      )}

      {rows.length === 0 ? (
        <div className="rounded-xl border border-line p-6 text-sm text-muted">
          Стадии не заданы. Добавьте первую стадию ниже.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-line text-[10px] uppercase tracking-wide text-faint">
                <th className="px-3 py-2 text-left font-semibold">Порядок</th>
                <th className="px-3 py-2 text-left font-semibold">Код</th>
                <th className="px-3 py-2 text-left font-semibold">Название</th>
                <th className="px-3 py-2 text-left font-semibold">Тип</th>
                <th className="px-3 py-2 text-right font-semibold">Вероятн. %</th>
                <th className="px-3 py-2 text-left font-semibold">Цвет</th>
                <th className="px-3 py-2 text-center font-semibold">Актив.</th>
                <th className="px-3 py-2 text-right font-semibold">Действия</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.code} className="border-b border-line last:border-0">
                  <td className="px-3 py-1.5">
                    <input
                      type="number"
                      value={r.sort_order}
                      onChange={(e) => patchRow(r.code, { sort_order: Number(e.target.value) })}
                      className="w-16 rounded-md border border-line bg-canvas px-2 py-1 tabular-nums"
                    />
                  </td>
                  <td className="px-3 py-1.5 font-mono text-[12px] text-muted">{r.code}</td>
                  <td className="px-3 py-1.5">
                    <input
                      value={r.title}
                      onChange={(e) => patchRow(r.code, { title: e.target.value })}
                      className="w-44 rounded-md border border-line bg-canvas px-2 py-1"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <select
                      value={r.kind}
                      onChange={(e) => patchRow(r.code, { kind: e.target.value as StageRow["kind"] })}
                      className="rounded-md border border-line bg-canvas px-2 py-1"
                    >
                      {KINDS.map((k) => (
                        <option key={k.id} value={k.id}>
                          {k.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={r.probability}
                      onChange={(e) => patchRow(r.code, { probability: Number(e.target.value) })}
                      className="w-16 rounded-md border border-line bg-canvas px-2 py-1 text-right tabular-nums"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      type="color"
                      value={r.color}
                      onChange={(e) => patchRow(r.code, { color: e.target.value })}
                      className="h-7 w-10 cursor-pointer rounded border border-line bg-canvas"
                    />
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    <input
                      type="checkbox"
                      checked={r.is_active}
                      onChange={(e) => patchRow(r.code, { is_active: e.target.checked })}
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <div className="flex justify-end gap-1.5">
                      <button
                        onClick={() => void save(r)}
                        disabled={busy}
                        className="rounded-md bg-accent px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-50"
                      >
                        Сохранить
                      </button>
                      <button
                        onClick={() => void remove(r)}
                        disabled={busy}
                        className="rounded-md border border-line px-2.5 py-1 text-xs font-semibold text-muted hover:text-red-600 disabled:opacity-50"
                      >
                        Удалить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Добавление новой стадии */}
      <div className="rounded-xl border border-dashed border-line p-3">
        <div className="mb-2 text-[12.5px] font-semibold text-ink">Новая стадия</div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-[11px] text-muted">
            Код
            <input
              value={draft.code}
              onChange={(e) => setDraft({ ...draft, code: e.target.value })}
              placeholder="напр. nurture"
              className="mt-0.5 block w-32 rounded-md border border-line bg-canvas px-2 py-1 text-sm"
            />
          </label>
          <label className="text-[11px] text-muted">
            Название
            <input
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              className="mt-0.5 block w-44 rounded-md border border-line bg-canvas px-2 py-1 text-sm"
            />
          </label>
          <label className="text-[11px] text-muted">
            Тип
            <select
              value={draft.kind}
              onChange={(e) => setDraft({ ...draft, kind: e.target.value as StageRow["kind"] })}
              className="mt-0.5 block rounded-md border border-line bg-canvas px-2 py-1 text-sm"
            >
              {KINDS.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-[11px] text-muted">
            Вероятн. %
            <input
              type="number"
              min={0}
              max={100}
              value={draft.probability}
              onChange={(e) => setDraft({ ...draft, probability: Number(e.target.value) })}
              className="mt-0.5 block w-20 rounded-md border border-line bg-canvas px-2 py-1 text-sm tabular-nums"
            />
          </label>
          <label className="text-[11px] text-muted">
            Порядок
            <input
              type="number"
              value={draft.sort_order}
              onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })}
              className="mt-0.5 block w-20 rounded-md border border-line bg-canvas px-2 py-1 text-sm tabular-nums"
            />
          </label>
          <button
            onClick={() => void add()}
            disabled={busy}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            Добавить
          </button>
        </div>
      </div>

      <p className="text-xs text-faint">
        Стадии — источник колонок доски и дефолтной вероятности (взвеш. прогноз). Тип «успех/отказ»
        задаёт терминальность; «условный отказ» реанимируется. Удаление стадии со сделками запрещено.
      </p>
    </div>
  );
}
