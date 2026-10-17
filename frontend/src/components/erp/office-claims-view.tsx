"use client";

import { useEffect, useRef, useState } from "react";

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

type ClaimFilters = {
  status: ClaimStatus | "";
  type: ClaimType | "";
};

function claimFilterKey(filters: ClaimFilters) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.type) params.set("claim_type", filters.type);
  return params.toString();
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
  const [claimResult, setClaimResult] = useState<{ filterKey: string; rows: LegalClaim[] } | null>(null);
  const [filterStatus, setFilterStatus] = useState<ClaimStatus | "">("");
  const [filterType, setFilterType] = useState<ClaimType | "">("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listError, setListError] = useState<{ filterKey: string; message: string } | null>(null);
  const [loadingFilterKey, setLoadingFilterKey] = useState<string | null>(null);
  const currentFilters = { status: filterStatus, type: filterType };
  const filtersRef = useRef<ClaimFilters>(currentFilters);
  const activeRequest = useRef<AbortController | null>(null);
  const requestVersion = useRef(0);
  const mounted = useRef(false);
  const currentFilterKey = claimFilterKey(currentFilters);
  const currentResult = claimResult?.filterKey === currentFilterKey ? claimResult : null;
  const currentListError = listError?.filterKey === currentFilterKey ? listError.message : null;
  const isLoading = loadingFilterKey === currentFilterKey;

  async function load(filters: ClaimFilters = filtersRef.current) {
    if (!mounted.current) return;
    const filterKey = claimFilterKey(filters);
    const version = ++requestVersion.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoadingFilterKey(filterKey);
    setListError(null);
    try {
      const res = await fetch(`/api/office/claims?${filterKey}`, {
        cache: "no-store",
        signal: controller.signal,
      });
      if (!res.ok) {
        if (!controller.signal.aborted && mounted.current && version === requestVersion.current) {
          setListError({ filterKey, message: `Ошибка ${res.status}` });
        }
        return;
      }
      const rows = (await res.json()) as LegalClaim[];
      if (!controller.signal.aborted && mounted.current && version === requestVersion.current) {
        setClaimResult({ filterKey, rows });
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
    setClaimResult(null);
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
            const status = e.target.value as ClaimStatus | "";
            filtersRef.current = { ...filtersRef.current, status };
            clearListForFilterChange();
            setFilterStatus(status);
          }}
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
          onChange={(e) => {
            const type = e.target.value as ClaimType | "";
            filtersRef.current = { ...filtersRef.current, type };
            clearListForFilterChange();
            setFilterType(type);
          }}
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
              <th className="px-4 py-3 text-left font-medium">Подана</th>
              <th className="px-4 py-3 text-right font-medium">Сумма BYN</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {!currentResult ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  {currentListError ? "Не удалось загрузить претензии" : "Загрузка списка…"}
                </td>
              </tr>
            ) : currentResult.rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  Претензий нет
                </td>
              </tr>
            ) : (
              currentResult.rows.map((c) => (
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
