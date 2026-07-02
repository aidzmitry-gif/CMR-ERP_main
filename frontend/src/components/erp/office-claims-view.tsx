"use client";

import { useEffect, useState } from "react";

type ClaimType = "overdue_payment" | "defect" | "shortage" | "other";
type ClaimStatus = "open" | "sent" | "responded" | "resolved" | "rejected";

interface LegalClaim {
  id: number;
  number: string;
  counterparty_name: string;
  claim_type: ClaimType;
  status: ClaimStatus;
  filed_at: string | null;
  amount_byn: string;
  description: string;
}

const CLAIM_TYPE_LABELS: Record<ClaimType, string> = {
  overdue_payment: "Просрочка оплаты",
  defect: "Брак",
  shortage: "Недопоставка",
  other: "Иное",
};

const STATUS_LABELS: Record<ClaimStatus, string> = {
  open: "Открыта",
  sent: "Направлена",
  responded: "Получен ответ",
  resolved: "Урегулирована",
  rejected: "Отклонена",
};

const STATUS_BADGE: Record<ClaimStatus, string> = {
  open: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
  sent: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  responded: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
  resolved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  rejected: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

const CLAIM_TYPES: ClaimType[] = ["overdue_payment", "defect", "shortage", "other"];
const CLAIM_STATUSES: ClaimStatus[] = ["open", "sent", "responded", "resolved", "rejected"];

interface CreateForm {
  counterparty_name: string;
  claim_type: ClaimType;
  amount_byn: string;
  filed_at: string;
  description: string;
  office_doc_ref: string;
}

const EMPTY_FORM: CreateForm = {
  counterparty_name: "",
  claim_type: "overdue_payment",
  amount_byn: "0.00",
  filed_at: "",
  description: "",
  office_doc_ref: "",
};

export function OfficeClaimsView() {
  const [claims, setClaims] = useState<LegalClaim[]>([]);
  const [filterStatus, setFilterStatus] = useState<ClaimStatus | "">("");
  const [filterType, setFilterType] = useState<ClaimType | "">("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const params = new URLSearchParams();
    if (filterStatus) params.set("status", filterStatus);
    if (filterType) params.set("claim_type", filterType);
    try {
      const res = await fetch(`/api/office/claims?${params.toString()}`, { cache: "no-store" });
      if (res.ok) setClaims(await res.json());
    } catch {
      /* сеть недоступна — показываем пустой список */
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStatus, filterType]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, string> = {
        counterparty_name: form.counterparty_name,
        claim_type: form.claim_type,
        amount_byn: form.amount_byn,
        description: form.description,
        office_doc_ref: form.office_doc_ref,
      };
      if (form.filed_at) body.filed_at = form.filed_at;

      const res = await fetch("/api/office/claims", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        setError(`Ошибка ${res.status}`);
      } else {
        setForm(EMPTY_FORM);
        setShowForm(false);
        await load();
      }
    } catch {
      setError("Ошибка сети");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-6">
      {/* Фильтры + кнопка создания */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value as ClaimStatus | "")}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">Все статусы</option>
          {CLAIM_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>

        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as ClaimType | "")}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">Все типы</option>
          {CLAIM_TYPES.map((t) => (
            <option key={t} value={t}>
              {CLAIM_TYPE_LABELS[t]}
            </option>
          ))}
        </select>

        <button
          onClick={() => setShowForm(!showForm)}
          className="ml-auto rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/90"
        >
          {showForm ? "Отмена" : "+ Претензия"}
        </button>
      </div>

      {/* Форма создания */}
      {showForm && (
        <form
          onSubmit={handleCreate}
          className="rounded-xl border border-line bg-surface p-4 shadow-sm"
        >
          <h3 className="mb-4 text-sm font-semibold text-ink">Новая претензия</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs text-muted">Контрагент *</label>
              <input
                required
                value={form.counterparty_name}
                onChange={(e) => setForm({ ...form, counterparty_name: e.target.value })}
                placeholder="ООО Поставщик"
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted">Тип претензии</label>
              <select
                value={form.claim_type}
                onChange={(e) => setForm({ ...form, claim_type: e.target.value as ClaimType })}
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
              >
                {CLAIM_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {CLAIM_TYPE_LABELS[t]}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted">Сумма, BYN</label>
              <input
                value={form.amount_byn}
                onChange={(e) => setForm({ ...form, amount_byn: e.target.value })}
                placeholder="0.00"
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted">Дата подачи</label>
              <input
                type="date"
                value={form.filed_at}
                onChange={(e) => setForm({ ...form, filed_at: e.target.value })}
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted">Ссылка на документ</label>
              <input
                value={form.office_doc_ref}
                onChange={(e) => setForm({ ...form, office_doc_ref: e.target.value })}
                placeholder="ДОК-2026-0001"
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </div>

            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs text-muted">Описание</label>
              <textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={2}
                placeholder="Краткое описание..."
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </div>
          </div>

          {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

          <div className="mt-4 flex justify-end">
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-accent px-5 py-1.5 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-60"
            >
              {saving ? "Сохранение…" : "Создать"}
            </button>
          </div>
        </form>
      )}

      {/* Таблица претензий */}
      <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-sunken text-xs text-muted">
              <th className="px-4 py-3 text-left font-medium">Номер</th>
              <th className="px-4 py-3 text-left font-medium">Контрагент</th>
              <th className="px-4 py-3 text-left font-medium">Тип</th>
              <th className="px-4 py-3 text-left font-medium">Статус</th>
              <th className="px-4 py-3 text-left font-medium">Подана</th>
              <th className="px-4 py-3 text-right font-medium">Сумма BYN</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {claims.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  Претензий нет
                </td>
              </tr>
            ) : (
              claims.map((c) => (
                <tr key={c.id} className="hover:bg-sunken/50">
                  <td className="px-4 py-3 font-mono text-xs text-accent">{c.number}</td>
                  <td className="px-4 py-3 font-medium text-ink">{c.counterparty_name}</td>
                  <td className="px-4 py-3 text-muted">
                    {CLAIM_TYPE_LABELS[c.claim_type] ?? c.claim_type}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[c.status] ?? ""}`}
                    >
                      {STATUS_LABELS[c.status] ?? c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted">{c.filed_at ?? "—"}</td>
                  <td className="px-4 py-3 text-right font-mono text-ink">{c.amount_byn}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
