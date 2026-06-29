"use client";

import { useEffect, useState } from "react";

type ContractType = "supply" | "service" | "lease" | "nda";
type ContractStatus = "active" | "expired" | "terminated";

interface LegalContract {
  id: number;
  number: string;
  counterparty_name: string;
  contract_type: ContractType;
  status: ContractStatus;
  signed_at: string | null;
  expires_at: string | null;
  amount_byn: string;
  description: string;
}

const CONTRACT_TYPE_LABELS: Record<ContractType, string> = {
  supply: "Поставка",
  service: "Услуги",
  lease: "Аренда",
  nda: "NDA",
};

const STATUS_LABELS: Record<ContractStatus, string> = {
  active: "Активный",
  expired: "Истёк",
  terminated: "Расторгнут",
};

const STATUS_BADGE: Record<ContractStatus, string> = {
  active: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  expired: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300",
  terminated: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

const CONTRACT_TYPES: ContractType[] = ["supply", "service", "lease", "nda"];
const CONTRACT_STATUSES: ContractStatus[] = ["active", "expired", "terminated"];

interface CreateForm {
  counterparty_name: string;
  contract_type: ContractType;
  signed_at: string;
  expires_at: string;
  amount_byn: string;
  description: string;
}

const EMPTY_FORM: CreateForm = {
  counterparty_name: "",
  contract_type: "supply",
  signed_at: "",
  expires_at: "",
  amount_byn: "0.00",
  description: "",
};

export function OfficeLegalView() {
  const [contracts, setContracts] = useState<LegalContract[]>([]);
  const [filterStatus, setFilterStatus] = useState<ContractStatus | "">("");
  const [filterType, setFilterType] = useState<ContractType | "">("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const params = new URLSearchParams();
    if (filterStatus) params.set("status", filterStatus);
    if (filterType) params.set("contract_type", filterType);
    try {
      const res = await fetch(`/api/office/contracts?${params.toString()}`, { cache: "no-store" });
      if (res.ok) setContracts(await res.json());
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
        contract_type: form.contract_type,
        amount_byn: form.amount_byn,
        description: form.description,
      };
      if (form.signed_at) body.signed_at = form.signed_at;
      if (form.expires_at) body.expires_at = form.expires_at;

      const res = await fetch("/api/office/contracts", {
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
          onChange={(e) => setFilterStatus(e.target.value as ContractStatus | "")}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">Все статусы</option>
          {CONTRACT_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>

        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as ContractType | "")}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">Все типы</option>
          {CONTRACT_TYPES.map((t) => (
            <option key={t} value={t}>
              {CONTRACT_TYPE_LABELS[t]}
            </option>
          ))}
        </select>

        <button
          onClick={() => setShowForm(!showForm)}
          className="ml-auto rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/90"
        >
          {showForm ? "Отмена" : "+ Договор"}
        </button>
      </div>

      {/* Форма создания */}
      {showForm && (
        <form
          onSubmit={handleCreate}
          className="rounded-xl border border-line bg-surface p-4 shadow-sm"
        >
          <h3 className="mb-4 text-sm font-semibold text-ink">Новый договор</h3>
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
              <label className="mb-1 block text-xs text-muted">Тип договора</label>
              <select
                value={form.contract_type}
                onChange={(e) => setForm({ ...form, contract_type: e.target.value as ContractType })}
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
              >
                {CONTRACT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {CONTRACT_TYPE_LABELS[t]}
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
              <label className="mb-1 block text-xs text-muted">Дата подписания</label>
              <input
                type="date"
                value={form.signed_at}
                onChange={(e) => setForm({ ...form, signed_at: e.target.value })}
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted">Дата истечения</label>
              <input
                type="date"
                value={form.expires_at}
                onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
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

      {/* Таблица договоров */}
      <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-sunken text-xs text-muted">
              <th className="px-4 py-3 text-left font-medium">Номер</th>
              <th className="px-4 py-3 text-left font-medium">Контрагент</th>
              <th className="px-4 py-3 text-left font-medium">Тип</th>
              <th className="px-4 py-3 text-left font-medium">Статус</th>
              <th className="px-4 py-3 text-left font-medium">Подписан</th>
              <th className="px-4 py-3 text-left font-medium">Истекает</th>
              <th className="px-4 py-3 text-right font-medium">Сумма, BYN</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {contracts.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-muted">
                  Договоров нет
                </td>
              </tr>
            ) : (
              contracts.map((c) => (
                <tr key={c.id} className="hover:bg-sunken/50">
                  <td className="px-4 py-3 font-mono text-xs text-accent">{c.number}</td>
                  <td className="px-4 py-3 font-medium text-ink">{c.counterparty_name}</td>
                  <td className="px-4 py-3 text-muted">
                    {CONTRACT_TYPE_LABELS[c.contract_type] ?? c.contract_type}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[c.status] ?? ""}`}
                    >
                      {STATUS_LABELS[c.status] ?? c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted">{c.signed_at ?? "—"}</td>
                  <td className="px-4 py-3 text-muted">{c.expires_at ?? "—"}</td>
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
