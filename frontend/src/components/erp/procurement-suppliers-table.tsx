"use client";

import clsx from "clsx";
import { Plus, RefreshCw, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { SourceTag } from "@/components/source-tag";
import { formatNumber } from "@/lib/format";
import {
  createSupplier,
  emptySupplier,
  fetchSuppliers,
  filterSuppliers,
  type Supplier,
  type SupplierInput,
  statusLabel,
  updateSupplier,
} from "@/lib/procurement-suppliers";

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-ink tabular-nums">{value}</div>
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  active: "bg-green-50 text-green-700 dark:bg-green-500/10 dark:text-green-300",
  blocked: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300",
};

type Draft = SupplierInput & { id?: number };

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-muted">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
      />
    </label>
  );
}

export function ProcurementSuppliersTable({ initial }: { initial: Supplier[] }) {
  const [rows, setRows] = useState<Supplier[]>(initial);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void fetchSuppliers().then((d) => {
      if (d) setRows(d); // null = ошибка fetch → не затираем SSR-данные
    });
  }, []);

  async function refresh() {
    setBusy(true);
    const d = await fetchSuppliers();
    if (d) setRows(d);
    setBusy(false);
  }

  const filtered = useMemo(() => filterSuppliers(rows, query), [rows, query]);
  const active = rows.filter((s) => s.status === "active").length;

  function openCreate() {
    setError("");
    setDraft({ ...emptySupplier() });
  }
  function openEdit(s: Supplier) {
    setError("");
    setDraft({ ...s });
  }

  async function save() {
    if (!draft || !draft.name.trim()) {
      setError("Имя поставщика обязательно");
      return;
    }
    setSaving(true);
    setError("");
    const { id, ...input } = draft;
    const saved = id ? await updateSupplier(id, input) : await createSupplier(input);
    setSaving(false);
    if (!saved) {
      setError("Не удалось сохранить — попробуйте ещё раз");
      return;
    }
    setDraft(null);
    await refresh();
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Профили поставщиков: условия оплаты, срок поставки, incoterms, статус. УНП — из MDM
          (эталон контрагента), здесь — закупочные атрибуты.
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={refresh}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
          >
            <RefreshCw size={15} className={clsx(busy && "animate-spin")} /> Обновить
          </button>
          <button
            onClick={openCreate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            <Plus size={15} /> Добавить
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3">
        <Kpi label="Поставщиков" value={formatNumber(rows.length)} />
        <Kpi label="Активных" value={formatNumber(active)} />
        <Kpi label="Заблокировано" value={formatNumber(rows.length - active)} />
      </div>

      <div className="mt-5 flex items-center">
        <div className="relative ml-auto">
          <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск: имя, УНП, страна"
            className="w-64 rounded-lg border border-line bg-surface py-2 pl-8 pr-3 text-sm text-ink outline-none focus:border-accent"
          />
        </div>
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Поставщик</th>
              <th className="px-4 py-2 font-medium">Страна</th>
              <th className="px-4 py-2 font-medium">Условия оплаты</th>
              <th className="px-4 py-2 text-right font-medium">Срок, дн</th>
              <th className="px-4 py-2 font-medium">Incoterms</th>
              <th className="px-4 py-2 font-medium">Статус</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted">
                  {rows.length === 0 ? "Поставщиков пока нет — добавьте первого" : "Ничего не найдено"}
                </td>
              </tr>
            )}
            {filtered.map((s) => (
              <tr
                key={s.id}
                onClick={() => openEdit(s)}
                className="cursor-pointer border-b border-line last:border-0 hover:bg-sunken/50"
              >
                <td className="px-4 py-2.5">
                  <div className="font-medium text-ink">{s.name}</div>
                  {s.unp && <SourceTag entity="Контрагент" source="mdm/1c" unp={s.unp} />}
                </td>
                <td className="px-4 py-2.5 text-muted">
                  {s.flag} {s.country}
                </td>
                <td className="px-4 py-2.5 text-muted">{s.payment_terms || "—"}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                  {s.lead_time_days ?? "—"}
                </td>
                <td className="px-4 py-2.5 text-muted">{s.incoterms || "—"}</td>
                <td className="px-4 py-2.5">
                  <span
                    className={clsx(
                      "rounded-full px-2 py-0.5 text-xs font-medium",
                      STATUS_TONE[s.status] ?? "bg-sunken text-muted",
                    )}
                  >
                    {statusLabel(s.status)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {draft && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={() => setDraft(null)}>
          <div
            className="h-full w-full max-w-md overflow-auto bg-canvas p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-ink">
                {draft.id ? "Поставщик" : "Новый поставщик"}
              </h2>
              <button onClick={() => setDraft(null)} className="text-muted hover:text-ink">
                <X size={18} />
              </button>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3">
              <Field label="Название*" value={draft.name} onChange={(v) => setDraft({ ...draft, name: v })} />
              <div className="grid grid-cols-2 gap-3">
                <Field label="УНП (MDM)" value={draft.unp} onChange={(v) => setDraft({ ...draft, unp: v })} />
                <Field label="Страна" value={draft.country} onChange={(v) => setDraft({ ...draft, country: v })} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Флаг (emoji)" value={draft.flag} onChange={(v) => setDraft({ ...draft, flag: v })} />
                <Field label="Incoterms" value={draft.incoterms} onChange={(v) => setDraft({ ...draft, incoterms: v })} />
              </div>
              <Field label="Контактное лицо" value={draft.contact_person} onChange={(v) => setDraft({ ...draft, contact_person: v })} />
              <div className="grid grid-cols-2 gap-3">
                <Field label="Телефон" value={draft.phone} onChange={(v) => setDraft({ ...draft, phone: v })} />
                <Field label="Email" value={draft.email} onChange={(v) => setDraft({ ...draft, email: v })} />
              </div>
              <Field
                label="Условия оплаты"
                value={draft.payment_terms}
                onChange={(v) => setDraft({ ...draft, payment_terms: v })}
                placeholder="30% предоплата / 70% по факту"
              />
              <div className="grid grid-cols-2 gap-3">
                <Field
                  label="Срок поставки, дн"
                  value={draft.lead_time_days == null ? "" : String(draft.lead_time_days)}
                  onChange={(v) =>
                    setDraft({ ...draft, lead_time_days: v.trim() === "" ? null : Number(v) || 0 })
                  }
                />
                <label className="block">
                  <span className="text-[11px] text-muted">Статус</span>
                  <select
                    value={draft.status}
                    onChange={(e) => setDraft({ ...draft, status: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                  >
                    <option value="active">Активен</option>
                    <option value="blocked">Заблокирован</option>
                  </select>
                </label>
              </div>
              <Field label="Заметки" value={draft.notes} onChange={(v) => setDraft({ ...draft, notes: v })} />
            </div>

            {error && <div className="mt-3 text-sm text-red-600">{error}</div>}

            <div className="mt-5 flex gap-2">
              <button
                onClick={save}
                disabled={saving}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
              >
                {saving ? "Сохранение…" : "Сохранить"}
              </button>
              <button
                onClick={() => setDraft(null)}
                className="rounded-lg border border-line bg-surface px-4 py-2 text-sm font-medium text-muted hover:bg-sunken"
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
