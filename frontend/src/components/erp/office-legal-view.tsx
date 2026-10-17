"use client";

import { useEffect, useRef, useState } from "react";

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

type ContractFilters = {
  status: ContractStatus | "";
  type: ContractType | "";
};

function contractFilterKey(filters: ContractFilters) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.type) params.set("contract_type", filters.type);
  return params.toString();
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
  const [contractResult, setContractResult] = useState<{ filterKey: string; rows: LegalContract[] } | null>(null);
  const [filterStatus, setFilterStatus] = useState<ContractStatus | "">("");
  const [filterType, setFilterType] = useState<ContractType | "">("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listError, setListError] = useState<{ filterKey: string; message: string } | null>(null);
  const [loadingFilterKey, setLoadingFilterKey] = useState<string | null>(null);
  const currentFilters = { status: filterStatus, type: filterType };
  const filtersRef = useRef<ContractFilters>(currentFilters);
  const activeRequest = useRef<AbortController | null>(null);
  const requestVersion = useRef(0);
  const mounted = useRef(false);
  const currentFilterKey = contractFilterKey(currentFilters);
  const currentResult = contractResult?.filterKey === currentFilterKey ? contractResult : null;
  const currentListError = listError?.filterKey === currentFilterKey ? listError.message : null;
  const isLoading = loadingFilterKey === currentFilterKey;

  async function load(filters: ContractFilters = filtersRef.current) {
    if (!mounted.current) return;
    const filterKey = contractFilterKey(filters);
    const version = ++requestVersion.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoadingFilterKey(filterKey);
    setListError(null);
    try {
      const res = await fetch(`/api/office/contracts?${filterKey}`, {
        cache: "no-store",
        signal: controller.signal,
      });
      if (!res.ok) {
        if (!controller.signal.aborted && mounted.current && version === requestVersion.current) {
          setListError({ filterKey, message: `Ошибка ${res.status}` });
        }
        return;
      }
      const rows = (await res.json()) as LegalContract[];
      if (!controller.signal.aborted && mounted.current && version === requestVersion.current) {
        setContractResult({ filterKey, rows });
      }
    } catch {
      if (!controller.signal.aborted && mounted.current && version === requestVersion.current) {
        setListError({ filterKey, message: "Ошибка сети" });
      }
    } finally {
      if (!controller.signal.aborted && mounted.current && version === requestVersion.current) {
        setLoadingFilterKey(null);
      }
    }
  }

  function clearListForFilterChange() {
    requestVersion.current += 1;
    activeRequest.current?.abort();
    setLoadingFilterKey(null);
    setListError(null);
    setContractResult(null);
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      activeRequest.current?.abort();
    };
  }, []);

  useEffect(() => {
    void load({ status: filterStatus, type: filterType });
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
        if (mounted.current) setError(`Ошибка ${res.status}`);
      } else if (mounted.current) {
        setForm(EMPTY_FORM);
        setShowForm(false);
        await load(filtersRef.current);
      }
    } catch {
      if (mounted.current) setError("Ошибка сети");
    } finally {
      if (mounted.current) setSaving(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-6">
      {/* Фильтры + кнопка создания */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={filterStatus}
          onChange={(e) => {
            const status = e.target.value as ContractStatus | "";
            filtersRef.current = { ...filtersRef.current, status };
            clearListForFilterChange();
            setFilterStatus(status);
          }}
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
          onChange={(e) => {
            const type = e.target.value as ContractType | "";
            filtersRef.current = { ...filtersRef.current, type };
            clearListForFilterChange();
            setFilterType(type);
          }}
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
        {currentListError && (
          <div role="alert" className="flex flex-wrap items-center gap-3 border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <span>{currentListError}</span>
            {currentResult && <span>Показаны ранее загруженные данные.</span>}
            <button
              type="button"
              onClick={() => void load(filtersRef.current)}
              disabled={isLoading}
              className="rounded border border-red-300 px-3 py-1 font-medium hover:bg-red-100 disabled:opacity-60"
            >
              Повторить
            </button>
          </div>
        )}
        {isLoading && currentResult && (
          <p role="status" className="px-4 py-2 text-xs text-muted">Обновление списка…</p>
        )}
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
            {!currentResult ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-muted">
                  {currentListError ? "Не удалось загрузить договоры" : "Загрузка списка…"}
                </td>
              </tr>
            ) : currentResult.rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-muted">
                  Договоров нет
                </td>
              </tr>
            ) : (
              currentResult.rows.map((c) => (
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
