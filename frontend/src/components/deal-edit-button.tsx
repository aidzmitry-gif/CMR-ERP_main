"use client";

import { Pencil, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { updateDeal } from "@/lib/api";
import { useUnsavedDocumentGuard } from "@/lib/use-unsaved-document-guard";

const INPUT = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";

export function DealEditButton({
  dealId,
  title,
  amount,
  nextStep,
  dealDate,
  shipDeadline = "",
  penaltyRatePct = null,
  penaltyCapPct = null,
  penaltyTerms = "",
}: {
  dealId: string;
  title: string;
  amount: number;
  nextStep: string;
  dealDate: string;
  shipDeadline?: string;
  penaltyRatePct?: number | null;
  penaltyCapPct?: number | null;
  penaltyTerms?: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const initial = {
    title,
    amount,
    next_step: nextStep,
    deal_date: dealDate,
    ship_deadline: shipDeadline,
    penalty_rate_pct: penaltyRatePct != null ? String(penaltyRatePct) : "",
    penalty_cap_pct: penaltyCapPct != null ? String(penaltyCapPct) : "",
    penalty_terms: penaltyTerms,
  };
  const [form, setForm] = useState(initial);
  const [baseline, setBaseline] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const confirmClose = useUnsavedDocumentGuard(open && JSON.stringify(form) !== JSON.stringify(baseline));

  function edit() {
    setForm(initial);
    setBaseline(initial);
    setError("");
    setOpen(true);
  }

  function close() {
    if (!submitting.current && confirmClose()) setOpen(false);
  }

  async function save() {
    if (submitting.current) return;
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      const confirmed = await updateDeal(dealId, {
        title: form.title,
        amount: Number(form.amount),
        next_step: form.next_step,
        deal_date: form.deal_date,
        // Крайняя дата отгрузки + штраф; пустое поле → null. Смена даты → сигнал в закупки (бэк).
        ship_deadline: form.ship_deadline || null,
        penalty_rate_pct: form.penalty_rate_pct === "" ? null : Number(form.penalty_rate_pct),
        penalty_cap_pct: form.penalty_cap_pct === "" ? null : Number(form.penalty_cap_pct),
        penalty_terms: form.penalty_terms || null,
      });
      if (!confirmed) { setError("Сервер не подтвердил сохранение. Изменения оставлены в форме."); return; }
      setOpen(false);
      router.refresh();
    } catch {
      setError("Результат сохранения неизвестен. Проверьте сделку перед повторной отправкой.");
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }

  return (
    <>
      <button
        onClick={edit}
        title="Редактировать сделку"
        className="flex h-8 w-8 items-center justify-center rounded-lg border border-line text-muted hover:bg-sunken"
      >
        <Pencil size={15} />
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onClick={close}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-2xl bg-surface p-5 shadow-pop"
          >
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-ink">Редактировать сделку</h3>
              <button onClick={close} disabled={saving} className="text-faint hover:text-muted">
                <X size={20} />
              </button>
            </div>
            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-muted">Описание</span>
                <input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  className={INPUT}
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-muted">Сумма сделки</span>
                  <input
                    type="number"
                    min={0}
                    value={form.amount}
                    onChange={(e) => setForm({ ...form, amount: Number(e.target.value) })}
                    className={INPUT}
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-muted">Дата</span>
                  <input
                    value={form.deal_date}
                    onChange={(e) => setForm({ ...form, deal_date: e.target.value })}
                    placeholder="12.05.2024"
                    className={INPUT}
                  />
                </label>
              </div>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-muted">Следующий шаг</span>
                <input
                  type="datetime-local"
                  value={form.next_step}
                  onChange={(e) => setForm({ ...form, next_step: e.target.value })}
                  className={INPUT}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-muted">
                  Крайняя дата отгрузки
                </span>
                <input
                  type="date"
                  value={form.ship_deadline}
                  onChange={(e) => setForm({ ...form, ship_deadline: e.target.value })}
                  className={INPUT}
                />
                <span className="mt-1 block text-[11px] text-faint">
                  Уходит сигналом в закупки — чтобы успели к сроку.
                </span>
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-muted">Штраф, %/день</span>
                  <input
                    type="number"
                    min={0}
                    max={9999.99}
                    step={0.01}
                    value={form.penalty_rate_pct}
                    onChange={(e) => setForm({ ...form, penalty_rate_pct: e.target.value })}
                    placeholder="0.1"
                    className={INPUT}
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-muted">
                    Потолок, % от суммы
                  </span>
                  <input
                    type="number"
                    min={0}
                    max={9999.99}
                    step={0.01}
                    value={form.penalty_cap_pct}
                    onChange={(e) => setForm({ ...form, penalty_cap_pct: e.target.value })}
                    placeholder="10"
                    className={INPUT}
                  />
                </label>
              </div>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-muted">
                  Условия штрафа (примечание)
                </span>
                <input
                  value={form.penalty_terms}
                  onChange={(e) => setForm({ ...form, penalty_terms: e.target.value })}
                  placeholder="0.1% за каждый день просрочки, не более 10%"
                  maxLength={512}
                  className={INPUT}
                />
              </label>
            </div>
            {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={close}
                disabled={saving}
                className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-muted"
              >
                Отмена
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
              >
                {saving ? "Сохранение..." : "Сохранить и закрыть"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
