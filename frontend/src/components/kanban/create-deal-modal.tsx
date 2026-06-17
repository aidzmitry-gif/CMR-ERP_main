"use client";

import { Search, X } from "lucide-react";
import { useState } from "react";
import { type DealInput, lookupCounterparty } from "@/lib/api";
import type { Stage } from "@/lib/types";

const PRIORITIES = ["Высокий", "Средний", "Низкий"];
const INPUT = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
    </label>
  );
}

export function CreateDealModal({
  stages,
  defaultStage,
  onClose,
  onCreate,
}: {
  stages: Stage[];
  defaultStage: string;
  onClose: () => void;
  onCreate: (input: DealInput) => Promise<boolean>;
}) {
  const [form, setForm] = useState<DealInput>({
    number: "",
    counterparty: "",
    title: "",
    amount: 0,
    priority: "Средний",
    stage: defaultStage,
    owner: "",
    next_step: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unp, setUnp] = useState("");
  const [looking, setLooking] = useState(false);
  const [lookupMsg, setLookupMsg] = useState<string | null>(null);

  function set<K extends keyof DealInput>(key: K, value: DealInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function onLookup() {
    if (!unp.trim()) return;
    setLooking(true);
    setLookupMsg(null);
    const info = await lookupCounterparty(unp.trim());
    setLooking(false);
    if (info) {
      set("counterparty", info.name);
      setLookupMsg(`${info.name} · ${info.address} · ${info.status}`);
    } else {
      setLookupMsg("По УНП в реестре ничего не найдено");
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const ok = await onCreate(form);
    setSaving(false);
    if (!ok) setError("Не удалось создать сделку (возможно, номер уже занят).");
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onClick={onClose}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="w-full max-w-md rounded-2xl bg-surface p-5 shadow-pop"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-ink">Новая сделка</h3>
          <button type="button" onClick={onClose} className="text-faint hover:text-muted">
            <X size={20} />
          </button>
        </div>

        <div className="space-y-3">
          <Field label="Номер">
            <input required value={form.number} onChange={(e) => set("number", e.target.value)} placeholder="CRM-2024-0200" className={INPUT} />
          </Field>
          <Field label="УНП (поиск в реестре ЕГР)">
            <div className="flex gap-2">
              <input
                value={unp}
                onChange={(e) => setUnp(e.target.value)}
                placeholder="191234567"
                className={INPUT}
              />
              <button
                type="button"
                onClick={onLookup}
                disabled={looking}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-accent px-3 py-2 text-sm font-medium text-accent-ink hover:bg-accent-soft disabled:opacity-60"
              >
                <Search size={15} /> {looking ? "..." : "Найти"}
              </button>
            </div>
          </Field>
          {lookupMsg && <p className="-mt-1 text-xs text-muted">{lookupMsg}</p>}
          <Field label="Компания">
            <input required value={form.counterparty} onChange={(e) => set("counterparty", e.target.value)} placeholder="ООО ..." className={INPUT} />
          </Field>
          <Field label="Описание">
            <input required value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="Поставка ..." className={INPUT} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Сумма, ₽">
              <input type="number" min={0} value={form.amount} onChange={(e) => set("amount", Number(e.target.value))} className={INPUT} />
            </Field>
            <Field label="Приоритет">
              <select value={form.priority} onChange={(e) => set("priority", e.target.value)} className={INPUT}>
                {PRIORITIES.map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Стадия">
              <select value={form.stage} onChange={(e) => set("stage", e.target.value)} className={INPUT}>
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Ответственный">
              <input value={form.owner} onChange={(e) => set("owner", e.target.value)} placeholder="Иванов И.И." className={INPUT} />
            </Field>
          </div>
        </div>

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-muted">
            Отмена
          </button>
          <button type="submit" disabled={saving} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60">
            {saving ? "Сохранение..." : "Создать"}
          </button>
        </div>
      </form>
    </div>
  );
}
