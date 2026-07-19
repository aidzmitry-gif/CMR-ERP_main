"use client";

import { useCallback, useEffect, useState } from "react";

import { SourceTag } from "@/components/source-tag";
import { formatByn } from "@/lib/format";

// ──────────────────────────── Контракты ответов /finance/* ────────────────────────────

// Money-поля — строки BYN (backend отдаёт Decimal→str, деньги не через float).
// Проценты (pct) — остаются number: это не деньги.
interface FinanceSummary {
  currency: string;
  margin: {
    revenue: string;
    landed: string;
    landed_gross?: string;
    claim_refund?: string;
    freight: string;
    gross: string;
    pct: number | null;
  };
  cash: {
    inflow: string;
    outflow: string;
    net: string;
    received: string;
    pending_receivable: string;
    freight_refund: string;
  };
  costs: { kind: string; label: string; amount: string }[];
}

interface ReconDealResp {
  deal_id: number;
  finance_landed: string;
  facade_landed: string | null;
  delta: string | null;
  revenue: string;
  gross_finance: string;
  level: string;
  source_facade_available: boolean;
  currency: string;
}

interface Payment {
  id: number;
  ref: string;
  amount: string;
  status: string;
  kind: string;
  due_date: string | null;
  paid_at: string | null;
  deal_id: number | null;
  counterparty_ref: string | null;
  outstanding: string | null;
  is_overdue: boolean | null;
}

interface AgingSide {
  buckets: Record<string, string>;
  total: string;
}
interface AgingResp {
  as_of: string;
  currency: string;
  ar: AgingSide;
  ap: AgingSide;
}

interface CashflowWeek {
  week_start: string;
  inflow: string;
  outflow: string;
  net: string;
  cumulative: string;
}
interface CashflowBucket {
  bucket_start: string;
  inflow: string;
  outflow: string;
  net: string;
  cumulative: string;
}
interface CashflowResp {
  as_of: string;
  currency: string;
  mode?: "week" | "day";
  bucket_size_days?: number;
  account_id?: number | null;
  opening_balance: string;
  weeks: CashflowWeek[];
  buckets?: CashflowBucket[];
  not_dated: { inflow: string; outflow: string };
}

interface BankAccount {
  id: number;
  code: string;
  title: string;
  currency: string;
  opening_balance: string;
  opening_at: string | null;
  is_active: boolean;
}

interface MarginRow {
  key: number | string | null;
  revenue: string;
  // landed/gross = null, когда себестоимость не атрибутирована к группе (cogs_known=false):
  // показываем «—», а не завышенную прибыль как COGS=0.
  landed: string | null;
  freight: string;
  gross: string | null;
  pct: number | null;
  cogs_known?: boolean;
}
interface MarginResp {
  currency: string;
  items: MarginRow[];
}

interface ReconResp {
  as_of: string;
  source: string;
  source_available: boolean;
  matched: { ref: string; amount: string; counterparty_ref: string | null }[];
  only_in_erp: { ref: string; amount: string; counterparty_ref: string | null }[];
  only_in_1c: { ref: string | null; amount: string; counterparty_ref: string | null }[];
}

// ──────────────────────────── Подсобки ────────────────────────────

const KIND_LABEL: Record<string, string> = {
  receivable: "Счёт к получению",
  freight: "Фрахт",
  freight_refund: "Возврат фрахта",
  landed: "Себестоимость",
  claim_refund: "Компенсация по претензии",
  po_planned: "PO планируемый",
};

const BUCKETS = ["current", "1-30", "31-60", "61-90", "90+", "no_due"] as const;
const BUCKET_LABEL: Record<string, string> = {
  current: "Текущая",
  "1-30": "1–30 дн.",
  "31-60": "31–60 дн.",
  "61-90": "61–90 дн.",
  "90+": "90+ дн.",
  no_due: "Без срока",
};

function isInflow(p: Payment): boolean {
  const amount = parseFloat(p.amount);
  return p.kind === "receivable" ? amount >= 0 : amount < 0;
}

function StatusBadge({ status, overdue }: { status: string; overdue?: boolean | null }) {
  const effective = overdue ? "overdue" : status;
  const styles: Record<string, string> = {
    planned: "bg-sunken text-muted",
    pending: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    partial: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200",
    paid: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
    overdue: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",
  };
  const label: Record<string, string> = {
    planned: "план",
    pending: "ожидает",
    partial: "частично",
    paid: "оплачен",
    overdue: "просрочен",
  };
  return (
    <span
      className={`rounded-md px-2 py-0.5 text-xs font-medium ${styles[effective] ?? "bg-sunken text-muted"}`}
    >
      {label[effective] ?? effective}
    </span>
  );
}

function Card({ title, value, tone }: { title: string; value: string; tone?: "pos" | "neg" }) {
  const color = tone === "pos" ? "text-emerald-600" : tone === "neg" ? "text-rose-600" : "text-ink";
  return (
    <div className="rounded-xl bg-surface p-4 shadow-card">
      <div className="text-xs font-medium text-muted">{title}</div>
      <div className={`mt-1 text-lg font-bold ${color}`}>{value}</div>
    </div>
  );
}

type TabId =
  | "summary"
  | "payments"
  | "aging"
  | "cashflow"
  | "calendar"
  | "margin"
  | "pnl"
  | "dds"
  | "balance"
  | "reconcile";
const TABS: { id: TabId; label: string }[] = [
  { id: "summary", label: "Касса и маржа" },
  { id: "payments", label: "Платежи" },
  { id: "aging", label: "Aging" },
  { id: "cashflow", label: "Cash-flow" },
  { id: "calendar", label: "Календарь" },
  { id: "margin", label: "Маржа" },
  { id: "pnl", label: "P&L" },
  { id: "dds", label: "ДДС" },
  { id: "balance", label: "Баланс" },
  { id: "reconcile", label: "Сверка 1С" },
];

// ──────────────────────────── Главный экран ────────────────────────────

export function FinanceView() {
  const [tab, setTab] = useState<TabId>("summary");

  return (
    <main className="flex-1 overflow-auto p-6">
      <div>
        <h1 className="text-xl font-bold text-ink">Финансы</h1>
        <p className="mt-1 text-sm text-muted">
          Операционный срез: касса (ДДС-lite), фактическая маржа, AR/AP-aging, прогноз
          движения денег и сверка с 1С. Учёт/НДС/ЭСЧФ остаются в 1С.
        </p>
      </div>

      <div className="mt-4 flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              tab === t.id
                ? "border-ink text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {tab === "summary" && <SummaryTab />}
        {tab === "payments" && <PaymentsTab />}
        {tab === "aging" && <AgingTab />}
        {tab === "cashflow" && <CashflowTab />}
        {tab === "calendar" && <CalendarTab />}
        {tab === "margin" && <MarginTab />}
        {tab === "pnl" && <PnlTab />}
        {tab === "dds" && <DdsTab />}
        {tab === "balance" && <BalanceTab />}
        {tab === "reconcile" && <ReconcileTab />}
      </div>
    </main>
  );
}

// ──────────────────────────── Хук для GET-таба ────────────────────────────

function useFetch<T>(path: string): { data: T | null; loading: boolean; error: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(false);
    fetch(path, { cache: "no-store" })
      .then((r) => (r.ok ? (r.json() as Promise<T>) : Promise.reject()))
      .then((d) => {
        if (alive) setData(d);
      })
      .catch(() => alive && setError(true))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [path]);
  return { data, loading, error };
}

function State({ loading, error, empty, what }: { loading: boolean; error: boolean; empty?: boolean; what: string }) {
  if (loading) return <p className="text-sm text-muted">Загрузка…</p>;
  if (error)
    return (
      <p className="rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
        Нет связи с финансовым модулем — {what} недоступно.
      </p>
    );
  if (empty)
    return (
      <p className="rounded-xl bg-surface p-4 text-sm text-muted shadow-card">
        {what} пока пусто.
      </p>
    );
  return null;
}

// ──────────────────────────── Tab 1: Summary (касса + маржа + затраты + платежи) ────────────────────────────

function SummaryTab() {
  const summary = useFetch<FinanceSummary>("/api/finance/summary");
  const payments = useFetch<Payment[]>("/api/finance/payments");
  const stateBar = (
    <State
      loading={summary.loading || payments.loading}
      error={summary.error || payments.error}
      what="сводка"
    />
  );
  if (summary.loading || summary.error || !summary.data) return stateBar;
  const s = summary.data;
  const ps = payments.data ?? [];
  return (
    <>
      {/* Касса — ДДС-lite */}
      <h2 className="text-sm font-semibold text-muted">Касса (ДДС-lite)</h2>
      <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card title="Поступления" value={formatByn(parseFloat(s.cash.inflow))} tone="pos" />
        <Card title="Расходы" value={formatByn(parseFloat(s.cash.outflow))} tone="neg" />
        <Card
          title="Сальдо"
          value={formatByn(parseFloat(s.cash.net))}
          tone={parseFloat(s.cash.net) >= 0 ? "pos" : "neg"}
        />
        <Card
          title="К поступлению (счета)"
          value={formatByn(parseFloat(s.cash.pending_receivable))}
        />
      </div>

      {/* Фактическая маржа */}
      <h2 className="mt-6 text-sm font-semibold text-muted">Фактическая маржа (по фактам)</h2>
      <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card title="Выручка" value={formatByn(parseFloat(s.margin.revenue))} />
        <Card title="Себестоимость (landed)" value={formatByn(parseFloat(s.margin.landed))} />
        <Card title="Фрахт (нетто)" value={formatByn(parseFloat(s.margin.freight))} />
        <Card
          title={`Валовая прибыль${s.margin.pct != null ? ` · ${s.margin.pct.toFixed(1)}%` : ""}`}
          value={formatByn(parseFloat(s.margin.gross))}
          tone={parseFloat(s.margin.gross) >= 0 ? "pos" : "neg"}
        />
      </div>
      {parseFloat(s.margin.revenue) === 0 && (
        <p className="mt-2 text-xs text-muted">
          Выручки по фактам пока нет — маржа появится после первых проведённых счетов.
        </p>
      )}
      {parseFloat(s.margin.claim_refund ?? "0") > 0 && (
        <p className="mt-2 text-xs text-muted">
          Компенсация по претензии (приток от поставщика): +
          {formatByn(parseFloat(s.margin.claim_refund ?? "0"))} — уменьшает чистую себестоимость на
          эту величину.
        </p>
      )}

      {/* Затраты по типам */}
      <h2 className="mt-6 text-sm font-semibold text-muted">Затраты по типам</h2>
      <div className="mt-2 overflow-hidden rounded-xl bg-surface shadow-card">
        <table className="w-full text-sm">
          <tbody>
            {s.costs.map((c) => (
              <tr key={c.kind} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-ink">{c.label}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                  {formatByn(parseFloat(c.amount))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Движение платежей (краткое) */}
      <h2 className="mt-6 text-sm font-semibold text-muted">Движение платежей</h2>
      <div className="mt-2 overflow-hidden rounded-xl bg-surface shadow-card">
        <table className="w-full text-sm">
          <thead className="border-b border-line text-left text-xs text-muted">
            <tr>
              <th className="px-4 py-2.5 font-medium">Назначение</th>
              <th className="px-4 py-2.5 font-medium">Тип</th>
              <th className="px-4 py-2.5 font-medium">Статус</th>
              <th className="px-4 py-2.5 text-right font-medium">Сумма</th>
            </tr>
          </thead>
          <tbody>
            {ps.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-muted">
                  Платежей пока нет
                </td>
              </tr>
            )}
            {ps.map((p) => (
              <tr key={p.id} className="border-b border-line last:border-0 hover:bg-sunken">
                <td className="px-4 py-2.5 text-ink">{p.ref}</td>
                <td className="px-4 py-2.5 text-muted">{KIND_LABEL[p.kind] ?? p.kind}</td>
                <td className="px-4 py-2.5">
                  <StatusBadge status={p.status} overdue={p.is_overdue} />
                </td>
                <td
                  className={`px-4 py-2.5 text-right tabular-nums ${isInflow(p) ? "text-emerald-600" : "text-rose-600"}`}
                >
                  {isInflow(p) ? "+" : "−"}
                  {formatByn(Math.abs(parseFloat(p.amount)))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ──────────────────────────── Tab 2: Payments (детально + allocations) ────────────────────────────

function PaymentsTab() {
  const [bump, setBump] = useState(0);
  const { data, loading, error } = useFetch<Payment[]>(`/api/finance/payments?_=${bump}`);
  const [allocFor, setAllocFor] = useState<Payment | null>(null);
  const [allocAmt, setAllocAmt] = useState("");
  const [posting, setPosting] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);

  const onAllocate = useCallback(async () => {
    if (!allocFor) return;
    const amt = Number(allocAmt);
    if (!amt || amt <= 0) {
      setPostError("Сумма должна быть > 0");
      return;
    }
    setPosting(true);
    setPostError(null);
    try {
      const r = await fetch(`/api/finance/payments/${allocFor.id}/allocations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount: amt }),
      });
      if (!r.ok) throw new Error(String(r.status));
      setAllocFor(null);
      setAllocAmt("");
      setBump((b) => b + 1);
    } catch {
      setPostError("Не удалось зафиксировать поступление");
    } finally {
      setPosting(false);
    }
  }, [allocFor, allocAmt]);

  const bar = <State loading={loading} error={error} empty={!loading && !error && (data?.length ?? 0) === 0} what="платежи" />;
  if (loading || error || (data?.length ?? 0) === 0) return bar;
  return (
    <>
      <div className="overflow-hidden rounded-xl bg-surface shadow-card">
        <table className="w-full text-sm">
          <thead className="border-b border-line text-left text-xs text-muted">
            <tr>
              <th className="px-4 py-2.5 font-medium">Назначение</th>
              <th className="px-4 py-2.5 font-medium">Тип</th>
              <th className="px-4 py-2.5 font-medium">Срок</th>
              <th className="px-4 py-2.5 font-medium">Статус</th>
              <th className="px-4 py-2.5 text-right font-medium">Сумма</th>
              <th className="px-4 py-2.5 text-right font-medium">Остаток</th>
              <th className="px-4 py-2.5 text-right font-medium">Действие</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((p) => (
              <tr key={p.id} className="border-b border-line last:border-0 hover:bg-sunken">
                <td className="px-4 py-2.5 text-ink">{p.ref}</td>
                <td className="px-4 py-2.5 text-muted">{KIND_LABEL[p.kind] ?? p.kind}</td>
                <td className="px-4 py-2.5 text-muted">{p.due_date ?? "—"}</td>
                <td className="px-4 py-2.5">
                  <StatusBadge status={p.status} overdue={p.is_overdue} />
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                  {formatByn(parseFloat(p.amount))}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                  {p.outstanding != null ? formatByn(parseFloat(p.outstanding)) : "—"}
                </td>
                <td className="px-4 py-2.5 text-right">
                  {p.kind === "receivable" && p.status !== "paid" && (
                    <button
                      type="button"
                      className="rounded-md bg-ink/10 px-2 py-1 text-xs font-medium text-ink hover:bg-ink/20"
                      onClick={() => {
                        setAllocFor(p);
                        setAllocAmt(String(p.outstanding ?? p.amount));
                        setPostError(null);
                      }}
                    >
                      Зафиксировать поступление
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {allocFor && (
        <div className="mt-4 rounded-xl bg-surface p-4 shadow-card">
          <h3 className="text-sm font-semibold text-ink">
            Поступление по «{allocFor.ref}»
          </h3>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              type="number"
              step="0.01"
              min="0"
              value={allocAmt}
              onChange={(e) => setAllocAmt(e.target.value)}
              className="w-40 rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
            />
            <button
              type="button"
              disabled={posting}
              onClick={onAllocate}
              className="rounded-md bg-emerald-600 px-3 py-1 text-sm font-medium text-white disabled:opacity-60"
            >
              {posting ? "…" : "Зафиксировать"}
            </button>
            <button
              type="button"
              onClick={() => setAllocFor(null)}
              className="rounded-md bg-sunken px-3 py-1 text-sm text-muted"
            >
              Отмена
            </button>
            {postError && <span className="text-sm text-rose-600">{postError}</span>}
          </div>
        </div>
      )}
    </>
  );
}

// ──────────────────────────── Tab 3: Aging ────────────────────────────

function AgingTab() {
  const { data, loading, error } = useFetch<AgingResp>("/api/finance/aging");
  const bar = (
    <State
      loading={loading}
      error={error}
      empty={
        !loading &&
        !error &&
        data != null &&
        parseFloat(data.ar.total) === 0 &&
        parseFloat(data.ap.total) === 0
      }
      what="aging"
    />
  );
  if (loading || error || !data || (parseFloat(data.ar.total) === 0 && parseFloat(data.ap.total) === 0))
    return bar;
  const isAccent = (b: string) => b === "61-90" || b === "90+";
  const Side = ({ title, side }: { title: string; side: AgingSide }) => (
    <div className="overflow-hidden rounded-xl bg-surface shadow-card">
      <div className="border-b border-line px-4 py-2.5 text-sm font-semibold text-ink">
        {title} · {formatByn(parseFloat(side.total))}
      </div>
      <table className="w-full text-sm">
        <tbody>
          {BUCKETS.map((b) => (
            <tr
              key={b}
              className={`border-b border-line last:border-0 ${
                isAccent(b) ? "bg-rose-50 dark:bg-rose-900/20" : ""
              }`}
            >
              <td className={`px-4 py-2.5 ${isAccent(b) ? "text-rose-700 dark:text-rose-300 font-medium" : "text-muted"}`}>
                {BUCKET_LABEL[b]}
              </td>
              <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                {formatByn(parseFloat(side.buckets[b] ?? "0"))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
  return (
    <>
      <p className="text-xs text-muted">На {data.as_of}. Корзины 61–90 и 90+ — критический срок.</p>
      <div className="mt-2 grid gap-4 md:grid-cols-2">
        <Side title="Дебиторка (AR)" side={data.ar} />
        <Side title="Кредиторка (AP)" side={data.ap} />
      </div>
    </>
  );
}

// ──────────────────────────── Tab 4: Cash-flow ────────────────────────────

function CashflowTab() {
  const { data, loading, error } = useFetch<CashflowResp>("/api/finance/cashflow-forecast?weeks=8");
  const bar = <State loading={loading} error={error} empty={!loading && !error && data?.weeks.every((w) => parseFloat(w.inflow) === 0 && parseFloat(w.outflow) === 0)} what="прогноз кэш-фло" />;
  if (loading || error || !data) return bar;
  const max = Math.max(
    1,
    ...data.weeks.map((w) => Math.max(parseFloat(w.inflow), parseFloat(w.outflow))),
  );
  return (
    <>
      <p className="text-xs text-muted">
        На {data.as_of}. Начальное сальдо: {formatByn(parseFloat(data.opening_balance))}. Не
        датировано: +{formatByn(parseFloat(data.not_dated.inflow))} / −
        {formatByn(parseFloat(data.not_dated.outflow))}.
      </p>
      <div className="mt-2 overflow-hidden rounded-xl bg-surface shadow-card">
        <table className="w-full text-sm">
          <thead className="border-b border-line text-left text-xs text-muted">
            <tr>
              <th className="px-4 py-2.5 font-medium">Неделя</th>
              <th className="px-4 py-2.5 text-right font-medium">Приток</th>
              <th className="px-4 py-2.5 text-right font-medium">Отток</th>
              <th className="px-4 py-2.5 text-right font-medium">Нетто</th>
              <th className="px-4 py-2.5 text-right font-medium">Кумулятив</th>
              <th className="px-4 py-2.5 font-medium" style={{ width: "30%" }}>
                График
              </th>
            </tr>
          </thead>
          <tbody>
            {data.weeks.map((w) => {
              const inW = `${(parseFloat(w.inflow) / max) * 50}%`;
              const outW = `${(parseFloat(w.outflow) / max) * 50}%`;
              return (
                <tr key={w.week_start} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 text-ink">{w.week_start}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-emerald-600">
                    +{formatByn(parseFloat(w.inflow))}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-rose-600">
                    −{formatByn(parseFloat(w.outflow))}
                  </td>
                  <td
                    className={`px-4 py-2.5 text-right tabular-nums ${
                      parseFloat(w.net) >= 0 ? "text-emerald-600" : "text-rose-600"
                    }`}
                  >
                    {formatByn(parseFloat(w.net))}
                  </td>
                  <td
                    className={`px-4 py-2.5 text-right tabular-nums ${
                      parseFloat(w.cumulative) >= 0 ? "text-ink" : "text-rose-600"
                    }`}
                  >
                    {formatByn(parseFloat(w.cumulative))}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex h-3 items-center gap-0.5">
                      <div className="h-2 rounded-l bg-emerald-500/70" style={{ width: inW }} />
                      <div className="h-2 rounded-r bg-rose-500/70" style={{ width: outW }} />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ──────────────────────────── Tab 5: Margin dashboard ────────────────────────────

function MarginTab() {
  const byDeal = useFetch<MarginResp>("/api/finance/margin/by-deal");
  const byCp = useFetch<MarginResp>("/api/finance/margin/by-counterparty");
  const Section = ({
    title,
    resp,
    keyLabel,
    isCounterparty,
  }: {
    title: string;
    resp: { data: MarginResp | null; loading: boolean; error: boolean };
    keyLabel: string;
    isCounterparty?: boolean;
  }) => {
    if (resp.loading) return <State loading={true} error={false} what={title.toLowerCase()} />;
    if (resp.error) return <State loading={false} error={true} what={title.toLowerCase()} />;
    const items = resp.data?.items ?? [];
    if (items.length === 0)
      return <State loading={false} error={false} empty what={title.toLowerCase()} />;
    return (
      <div className="overflow-hidden rounded-xl bg-surface shadow-card">
        <div className="border-b border-line px-4 py-2.5 text-sm font-semibold text-ink">{title}</div>
        <table className="w-full text-sm">
          <thead className="border-b border-line text-left text-xs text-muted">
            <tr>
              <th className="px-4 py-2.5 font-medium">{keyLabel}</th>
              <th className="px-4 py-2.5 text-right font-medium">Выручка</th>
              <th className="px-4 py-2.5 text-right font-medium">Landed</th>
              <th className="px-4 py-2.5 text-right font-medium">Фрахт</th>
              <th className="px-4 py-2.5 text-right font-medium">Валовая</th>
              <th className="px-4 py-2.5 text-right font-medium">%</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={String(row.key ?? "_na_")} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-ink">
                  {row.key == null ? (
                    <span className="text-muted">Не атрибутировано</span>
                  ) : isCounterparty ? (
                    <span className="inline-flex items-center gap-2">
                      <span>{String(row.key)}</span>
                      <SourceTag entity="counterparty" source="mdm" unp={String(row.key)} />
                    </span>
                  ) : (
                    <span>#{String(row.key)}</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                  {formatByn(parseFloat(row.revenue))}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                  {row.landed != null ? (
                    formatByn(parseFloat(row.landed))
                  ) : (
                    <span title="Себестоимость не привязана к сделке — маржа неизвестна">—</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                  {formatByn(parseFloat(row.freight))}
                </td>
                {row.gross != null ? (
                  <td
                    className={`px-4 py-2.5 text-right tabular-nums ${
                      parseFloat(row.gross) >= 0 ? "text-emerald-600" : "text-rose-600"
                    }`}
                  >
                    {formatByn(parseFloat(row.gross))}
                  </td>
                ) : (
                  <td
                    className="px-4 py-2.5 text-right tabular-nums text-muted"
                    title="Себестоимость не атрибутирована к сделке — валовая прибыль неизвестна"
                  >
                    —
                  </td>
                )}
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                  {row.pct != null ? `${row.pct.toFixed(1)}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };
  return (
    <div className="grid gap-4">
      <ReconcileDealCard />
      <Section title="Маржа по сделкам" resp={byDeal} keyLabel="Сделка" />
      <Section title="Маржа по контрагентам" resp={byCp} keyLabel="Контрагент (УНП)" isCounterparty />
    </div>
  );
}

// ──────────────────────────── Сходимость маржи finance↔facade (FIN-A1) ────────────────────────────

function ReconcileDealCard() {
  const [dealId, setDealId] = useState("");
  const [items, setItems] = useState("");
  const [resp, setResp] = useState<ReconDealResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const onCheck = useCallback(async () => {
    const id = Number(dealId);
    if (!Number.isFinite(id) || id <= 0) return;
    setLoading(true);
    setError(false);
    setResp(null);
    try {
      const qs = new URLSearchParams({ deal_id: String(id) });
      if (items.trim()) qs.set("items", items.trim());
      const r = await fetch(`/api/finance/margin/reconcile-deal?${qs.toString()}`, {
        cache: "no-store",
      });
      if (!r.ok) throw new Error(String(r.status));
      setResp((await r.json()) as ReconDealResp);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [dealId, items]);

  return (
    <div className="overflow-hidden rounded-xl bg-surface shadow-card">
      <div className="border-b border-line px-4 py-2.5 text-sm font-semibold text-ink">
        Сходимость маржи finance ↔ landed-фасад
      </div>
      <div className="p-4">
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-muted">
            ID сделки
            <input
              type="number"
              value={dealId}
              onChange={(e) => setDealId(e.target.value)}
              className="w-32 rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              placeholder="42"
            />
          </label>
          <label className="flex flex-1 flex-col gap-1 text-xs text-muted">
            Позиции (SKU:qty через запятую — опц.)
            <input
              type="text"
              value={items}
              onChange={(e) => setItems(e.target.value)}
              className="min-w-[12rem] rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
              placeholder="S-001:2,S-002:5"
            />
          </label>
          <button
            type="button"
            disabled={loading || !dealId}
            onClick={onCheck}
            className="rounded-md bg-ink/10 px-3 py-1.5 text-sm font-medium text-ink hover:bg-ink/20 disabled:opacity-60"
          >
            {loading ? "Проверяю…" : "Проверить"}
          </button>
        </div>
        {error && (
          <p className="mt-3 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-900/30 dark:text-rose-200">
            Не удалось получить сверку — повторите.
          </p>
        )}
        {resp && (
          <div className="mt-3 space-y-2">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <Card title="Finance (landed)" value={formatByn(parseFloat(resp.finance_landed))} />
              <Card
                title="Facade (контроль)"
                value={resp.facade_landed != null ? formatByn(parseFloat(resp.facade_landed)) : "—"}
              />
              <Card
                title="Расхождение Δ"
                value={resp.delta != null ? formatByn(parseFloat(resp.delta)) : "—"}
                tone={resp.delta != null && parseFloat(resp.delta) !== 0 ? "neg" : "pos"}
              />
              <Card
                title="Валовая (по finance)"
                value={formatByn(parseFloat(resp.gross_finance))}
                tone={parseFloat(resp.gross_finance) >= 0 ? "pos" : "neg"}
              />
            </div>
            {!resp.source_facade_available ? (
              <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
                Landed-фасад недоступен (нет позиций или сервис не настроен) — Finance-сторона
                отдана честно, контрольная величина пуста.
              </p>
            ) : resp.delta != null && parseFloat(resp.delta) !== 0 ? (
              <p className="rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-900/30 dark:text-rose-200">
                Проводки finance отстали или опередили себестоимость — Δ ≠ 0. Перепосчитать landed.
              </p>
            ) : (
              <p className="rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200">
                Совпадает: проводки finance соответствуют landed-фасаду (агрегат по SKU).
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ──────────────────────────── Tab P&L (Р5) ────────────────────────────

interface PnlResp {
  from_date: string | null;
  to_date: string | null;
  currency: string;
  revenue: string;
  cogs: string;
  freight: string;
  gross_profit: string;
  payroll: string;
  opex: string;
  tax: string;
  bank_fee: string;
  operating_profit: string;
}

function PnlTab() {
  const today = new Date().toISOString().slice(0, 10);
  const firstOfYear = `${today.slice(0, 4)}-01-01`;

  const [from, setFrom] = useState(firstOfYear);
  const [to, setTo] = useState(today);
  const [query, setQuery] = useState(`period_from=${firstOfYear}&period_to=${today}`);

  const { data, loading, error } = useFetch<PnlResp>(`/api/finance/pnl?${query}`);

  const apply = useCallback(() => {
    setQuery(`period_from=${from}&period_to=${to}`);
  }, [from, to]);

  const downloadCsv = useCallback(() => {
    const url = `/api/finance/pnl?period_from=${from}&period_to=${to}&format=csv`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `pnl_${from}_${to}.csv`;
    a.click();
  }, [from, to]);

  const PNL_ROWS: { label: string; key: keyof PnlResp; bold?: boolean; indent?: boolean }[] = [
    { label: "Выручка (признанная, accrual)", key: "revenue" },
    { label: "Себестоимость (нетто)", key: "cogs", indent: true },
    { label: "Фрахт (нетто)", key: "freight", indent: true },
    { label: "ФОТ (опер. персонал)", key: "payroll", indent: true },
    { label: "Прочие операционные (Opex)", key: "opex", indent: true },
    { label: "Налоги", key: "tax", indent: true },
    { label: "Банковские расходы", key: "bank_fee", indent: true },
    { label: "Операционная прибыль", key: "operating_profit", bold: true },
  ];

  return (
    <div className="space-y-4">
      {/* Фильтр периода */}
      <div className="flex flex-wrap items-end gap-3 rounded-xl bg-surface p-4 shadow-card">
        <label className="flex flex-col gap-1 text-xs text-muted">
          С
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          По
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
          />
        </label>
        <button
          type="button"
          onClick={apply}
          className="rounded-md bg-ink/10 px-3 py-1.5 text-sm font-medium text-ink hover:bg-ink/20"
        >
          Применить
        </button>
        <button
          type="button"
          onClick={downloadCsv}
          className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-muted hover:text-ink"
        >
          Скачать CSV
        </button>
      </div>

      {/* Состояние */}
      {loading && <p className="text-sm text-muted">Загрузка…</p>}
      {error && (
        <p className="rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
          Нет данных P&L — проверьте подключение к финансовому модулю.
        </p>
      )}

      {/* Таблица P&L */}
      {data && !loading && (
        <div className="overflow-hidden rounded-xl bg-surface shadow-card">
          <div className="border-b border-line px-4 py-2.5 text-xs text-muted">
            Период: {data.from_date ?? "начало"} — {data.to_date ?? "сейчас"} · {data.currency}
          </div>
          <table className="w-full text-sm">
            <tbody>
              {PNL_ROWS.map(({ label, key, bold, indent }) => {
                const raw = data[key] as string;
                const val = parseFloat(raw);
                const isProfit = key === "operating_profit";
                const positive = val >= 0;
                return (
                  <tr
                    key={key}
                    className={`border-b border-line last:border-0 ${bold ? "bg-sunken" : ""}`}
                  >
                    <td
                      className={`px-4 py-3 ${indent ? "pl-8 text-muted" : "font-medium text-ink"} ${bold ? "font-semibold text-ink" : ""}`}
                    >
                      {label}
                    </td>
                    <td
                      className={`px-4 py-3 text-right tabular-nums ${
                        isProfit
                          ? positive
                            ? "font-bold text-emerald-600"
                            : "font-bold text-rose-600"
                          : "text-ink"
                      }`}
                    >
                      {parseFloat(raw) !== 0 || key === "operating_profit"
                        ? formatByn(val)
                        : <span className="text-muted">—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {data.revenue === "0.00" && (
            <p className="px-4 py-3 text-xs text-muted">
              Нет признанной выручки за период. Выручка признаётся по отгрузке (событие{" "}
              <code className="rounded bg-sunken px-1 py-0.5 font-mono text-xs">
                sales.deal.handoff
              </code>
              ).
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────── Tab: ДДС (Движение Денежных Средств) ────────────────────────────

interface DdsResp {
  period_from: string | null;
  period_to: string | null;
  currency: string;
  inflows: string;
  outflows: string;
  net_cashflow: string;
  bank_balance: string | null;
  breakdown: Record<string, string>;
}

const DDS_BREAKDOWN_LABELS: Record<string, string> = {
  receivable: "Поступления (счета)",
  payroll: "ФОТ",
  opex: "Прочие операционные",
  tax: "Налоги",
  bank_fee: "Банковские расходы",
  freight: "Фрахт",
  landed: "Себестоимость (landed)",
  po_planned: "PO планируемый",
};

function DdsTab() {
  const today = new Date().toISOString().slice(0, 10);
  const firstOfYear = `${today.slice(0, 4)}-01-01`;

  const [from, setFrom] = useState(firstOfYear);
  const [to, setTo] = useState(today);
  const [query, setQuery] = useState(`period_from=${firstOfYear}&period_to=${today}`);

  const { data, loading, error } = useFetch<DdsResp>(`/api/finance/cashflow?${query}`);

  const apply = useCallback(() => {
    setQuery(`period_from=${from}&period_to=${to}`);
  }, [from, to]);

  const downloadCsv = useCallback(() => {
    const url = `/api/finance/cashflow?period_from=${from}&period_to=${to}&format=csv`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `cashflow_${from}_${to}.csv`;
    a.click();
  }, [from, to]);

  const net = data ? parseFloat(data.net_cashflow) : 0;
  const netTone = net > 0 ? "pos" : net < 0 ? "neg" : undefined;

  return (
    <div className="space-y-4">
      {/* Фильтр периода */}
      <div className="flex flex-wrap items-end gap-3 rounded-xl bg-surface p-4 shadow-card">
        <label className="flex flex-col gap-1 text-xs text-muted">
          С
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          По
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
          />
        </label>
        <button
          type="button"
          onClick={apply}
          className="rounded-md bg-ink/10 px-3 py-1.5 text-sm font-medium text-ink hover:bg-ink/20"
        >
          Применить
        </button>
        <button
          type="button"
          onClick={downloadCsv}
          className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-muted hover:text-ink"
        >
          Скачать CSV
        </button>
      </div>

      {/* Состояние */}
      {loading && <p className="text-sm text-muted">Загрузка…</p>}
      {error && (
        <p className="rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
          Нет данных ДДС — проверьте подключение к финансовому модулю.
        </p>
      )}

      {data && !loading && (
        <>
          {/* Карточки-KPI */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card title="Поступления" value={formatByn(parseFloat(data.inflows))} tone="pos" />
            <Card title="Выбытия" value={formatByn(parseFloat(data.outflows))} tone="neg" />
            <Card title="Нетто" value={formatByn(net)} tone={netTone} />
            <div className="rounded-xl bg-surface p-4 shadow-card">
              <div className="text-xs font-medium text-muted">Остаток на счёте</div>
              <div className="mt-1 text-lg font-bold text-muted">
                {data.bank_balance != null ? formatByn(parseFloat(data.bank_balance)) : "—"}
              </div>
              {data.bank_balance == null && (
                <div className="mt-0.5 text-xs text-muted">нет связи с 1С</div>
              )}
            </div>
          </div>

          {/* Разбивка по видам */}
          <div className="overflow-hidden rounded-xl bg-surface shadow-card">
            <div className="border-b border-line px-4 py-2.5 text-xs text-muted">
              Разбивка · {data.period_from ?? "начало"} — {data.period_to ?? "сейчас"} ·{" "}
              {data.currency}
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line">
                  <th className="px-4 py-2 text-left font-medium text-muted">Вид</th>
                  <th className="px-4 py-2 text-right font-medium text-muted">Сумма, BYN</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.breakdown).map(([kind, amount]) => {
                  const val = parseFloat(amount);
                  const isInflow = kind === "receivable";
                  return (
                    <tr key={kind} className="border-b border-line last:border-0">
                      <td className="px-4 py-3 text-ink">
                        {DDS_BREAKDOWN_LABELS[kind] ?? kind}
                      </td>
                      <td
                        className={`px-4 py-3 text-right tabular-nums ${
                          val === 0
                            ? "text-muted"
                            : isInflow
                              ? "text-emerald-600"
                              : "text-rose-600"
                        }`}
                      >
                        {val !== 0 ? formatByn(val) : <span className="text-muted">—</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ──────────────────────────── Tab: Баланс (Р7) ────────────────────────────

interface BalanceResp {
  as_of: string;
  currency: string;
  accounts_receivable: string;
  cash: string | null;
  inventory_value: string | null;
  total_assets: string;
  accounts_payable: string;
  payroll_payable: string;
  tax_payable: string;
  total_liabilities: string;
  equity: string;
}

function BalanceTab() {
  const today = new Date().toISOString().slice(0, 10);
  const [asOf, setAsOf] = useState(today);
  const [query, setQuery] = useState(`as_of=${today}`);

  const { data, loading, error } = useFetch<BalanceResp>(`/api/finance/balance-sheet?${query}`);

  const apply = useCallback(() => {
    setQuery(`as_of=${asOf}`);
  }, [asOf]);

  const downloadCsv = useCallback(() => {
    const url = `/api/finance/balance-sheet?as_of=${asOf}&format=csv`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `balance_sheet_${asOf}.csv`;
    a.click();
  }, [asOf]);

  const equity = data ? parseFloat(data.equity) : 0;
  const equityTone = equity > 0 ? "pos" : equity < 0 ? "neg" : undefined;

  return (
    <div className="space-y-4">
      {/* Фильтр даты */}
      <div className="flex flex-wrap items-end gap-3 rounded-xl bg-surface p-4 shadow-card">
        <label className="flex flex-col gap-1 text-xs text-muted">
          На дату
          <input
            type="date"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            className="rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
          />
        </label>
        <button
          type="button"
          onClick={apply}
          className="rounded-md bg-ink/10 px-3 py-1.5 text-sm font-medium text-ink hover:bg-ink/20"
        >
          Применить
        </button>
        <button
          type="button"
          onClick={downloadCsv}
          className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-muted hover:text-ink"
        >
          Скачать CSV
        </button>
      </div>

      {loading && <p className="text-sm text-muted">Загрузка…</p>}
      {error && (
        <p className="rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
          Нет данных баланса — проверьте подключение к финансовому модулю.
        </p>
      )}

      {data && !loading && (
        <>
          {/* Две колонки: Активы / Пассивы */}
          <div className="grid gap-4 md:grid-cols-2">
            {/* Активы */}
            <div className="overflow-hidden rounded-xl bg-surface shadow-card">
              <div className="border-b border-line px-4 py-2.5 text-sm font-semibold text-ink">
                Активы · {data.currency}
              </div>
              <table className="w-full text-sm">
                <tbody>
                  <tr className="border-b border-line">
                    <td className="px-4 py-3 text-muted">Дебиторская задолженность</td>
                    <td className="px-4 py-3 text-right tabular-nums text-ink">
                      {formatByn(parseFloat(data.accounts_receivable))}
                    </td>
                  </tr>
                  <tr className="border-b border-line">
                    <td className="px-4 py-3 text-muted">Денежные средства (банк)</td>
                    <td className={`px-4 py-3 text-right tabular-nums ${data.cash == null ? "text-muted" : "text-ink"}`}>
                      {data.cash != null ? formatByn(parseFloat(data.cash)) : <span className="text-xs">нет связи с 1С</span>}
                    </td>
                  </tr>
                  <tr className="border-b border-line">
                    <td className="px-4 py-3 text-muted">Запасы (склад)</td>
                    <td className={`px-4 py-3 text-right tabular-nums ${data.inventory_value == null ? "text-muted" : "text-ink"}`}>
                      {data.inventory_value != null
                        ? formatByn(parseFloat(data.inventory_value))
                        : <span className="text-xs">нет связи с 1С</span>}
                    </td>
                  </tr>
                  <tr className="bg-sunken">
                    <td className="px-4 py-3 font-semibold text-ink">ИТОГО Активы</td>
                    <td className="px-4 py-3 text-right tabular-nums font-semibold text-ink">
                      {formatByn(parseFloat(data.total_assets))}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Пассивы */}
            <div className="overflow-hidden rounded-xl bg-surface shadow-card">
              <div className="border-b border-line px-4 py-2.5 text-sm font-semibold text-ink">
                Пассивы · {data.currency}
              </div>
              <table className="w-full text-sm">
                <tbody>
                  <tr className="border-b border-line">
                    <td className="px-4 py-3 text-muted">Кредиторская задолженность</td>
                    <td className="px-4 py-3 text-right tabular-nums text-ink">
                      {formatByn(parseFloat(data.accounts_payable))}
                    </td>
                  </tr>
                  <tr className="border-b border-line">
                    <td className="px-4 py-3 text-muted">Задолженность по ФОТ</td>
                    <td className="px-4 py-3 text-right tabular-nums text-ink">
                      {formatByn(parseFloat(data.payroll_payable))}
                    </td>
                  </tr>
                  <tr className="border-b border-line">
                    <td className="px-4 py-3 text-muted">Задолженность по налогам</td>
                    <td className="px-4 py-3 text-right tabular-nums text-ink">
                      {formatByn(parseFloat(data.tax_payable))}
                    </td>
                  </tr>
                  <tr className="bg-sunken">
                    <td className="px-4 py-3 font-semibold text-ink">ИТОГО Пассивы</td>
                    <td className="px-4 py-3 text-right tabular-nums font-semibold text-ink">
                      {formatByn(parseFloat(data.total_liabilities))}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Капитал */}
          <div className="overflow-hidden rounded-xl bg-surface shadow-card">
            <table className="w-full text-sm">
              <tbody>
                <tr>
                  <td className="px-4 py-4 text-base font-bold text-ink">Капитал (Equity)</td>
                  <td
                    className={`px-4 py-4 text-right text-base tabular-nums font-bold ${
                      equityTone === "pos"
                        ? "text-emerald-600"
                        : equityTone === "neg"
                          ? "text-rose-600"
                          : "text-ink"
                    }`}
                  >
                    {formatByn(equity)}
                  </td>
                </tr>
              </tbody>
            </table>
            <p className="px-4 pb-3 text-xs text-muted">
              На {data.as_of}. Equity = Активы − Пассивы. Поля «нет связи с 1С» считаются как 0 в итоге.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

// ──────────────────────────── Tab 6: Reconcile с 1С ────────────────────────────

function ReconcileTab() {
  const { data, loading, error } = useFetch<ReconResp>("/api/finance/reconcile-1c");
  if (loading) return <State loading={true} error={false} what="сверка с 1С" />;
  if (error) return <State loading={false} error={true} what="сверка с 1С" />;
  if (!data) return null;
  if (!data.source_available) {
    return (
      <div className="rounded-xl bg-surface p-6 text-sm text-muted shadow-card">
        <div className="flex items-center gap-2">
          <SourceTag entity="payments" source="1c" />
          <span>Сверка с 1С не настроена</span>
        </div>
        <p className="mt-2 text-xs">
          Шлюз 1С недоступен или метод чтения платежей не реализован. ERP не пишет в 1С —
          сверка появится, как только в `core/services/onec.py` будет включён `fetch_payments`.
        </p>
      </div>
    );
  }
  const Section = ({
    title,
    rows,
    tone,
  }: {
    title: string;
    rows: { ref: string | null; amount: string; counterparty_ref: string | null }[];
    tone?: "ok" | "warn";
  }) => (
    <div className="overflow-hidden rounded-xl bg-surface shadow-card">
      <div
        className={`border-b border-line px-4 py-2.5 text-sm font-semibold ${
          tone === "ok" ? "text-emerald-600" : tone === "warn" ? "text-amber-600" : "text-ink"
        }`}
      >
        {title} · {rows.length}
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-4 text-sm text-muted">Пусто</p>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.ref}-${i}`} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-ink">{r.ref ?? "—"}</td>
                <td className="px-4 py-2.5 text-muted">
                  {r.counterparty_ref ? (
                    <span className="inline-flex items-center gap-2">
                      <span>{r.counterparty_ref}</span>
                      <SourceTag entity="counterparty" source="1c" unp={r.counterparty_ref} />
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                  {formatByn(parseFloat(r.amount))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
  return (
    <>
      <p className="text-xs text-muted">
        На {data.as_of}. Источник: {data.source}. ERP-сторона только читает 1С — записи нет.
      </p>
      <div className="mt-2 grid gap-4 md:grid-cols-3">
        <Section title="Совпало" rows={data.matched} tone="ok" />
        <Section title="Только в ERP" rows={data.only_in_erp} tone="warn" />
        <Section title="Только в 1С" rows={data.only_in_1c} tone="warn" />
      </div>
    </>
  );
}

// ──────────────────────────── Tab 7: Платёжный календарь (Р4) ────────────────────────────

function CalendarTab() {
  const [accountId, setAccountId] = useState<string>("");
  const [days, setDays] = useState(30);
  const [bump, setBump] = useState(0);
  const accounts = useFetch<BankAccount[]>(
    `/api/finance/bank-accounts?active_only=true&_=${bump}`,
  );
  const qs = new URLSearchParams({
    mode: "day",
    days: String(days),
    _: String(bump),
  });
  if (accountId) qs.set("account_id", accountId);
  const calendar = useFetch<CashflowResp>(`/api/finance/cashflow-forecast?${qs.toString()}`);

  const accs = accounts.data ?? [];
  const buckets = calendar.data?.buckets ?? [];

  return (
    <div className="space-y-4">
      {/* Управление */}
      <div className="flex flex-wrap items-end gap-3 rounded-xl bg-surface p-4 shadow-card">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Банк-счёт
          <select
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            className="min-w-[14rem] rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
          >
            <option value="">Все счета (общий кэш)</option>
            {accs.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} · {a.title} ({a.currency})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Горизонт, дн.
          <input
            type="number"
            min={7}
            max={90}
            value={days}
            onChange={(e) => setDays(Math.max(1, Math.min(90, Number(e.target.value) || 30)))}
            className="w-24 rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
          />
        </label>
        <BankAccountForm onCreated={() => setBump((b) => b + 1)} />
      </div>

      {/* Состояние */}
      {accounts.error && (
        <p className="rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
          Не удалось загрузить список счетов.
        </p>
      )}
      {calendar.loading && <p className="text-sm text-muted">Загрузка календаря…</p>}
      {calendar.error && (
        <p className="rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
          Нет связи с прогнозом — попробуйте позже.
        </p>
      )}

      {/* Таблица день × приток/отток/нетто/кумулятив */}
      {calendar.data && buckets.length > 0 && (
        <div className="overflow-hidden rounded-xl bg-surface shadow-card">
          <div className="border-b border-line px-4 py-2.5 text-sm text-muted">
            На {calendar.data.as_of}. Начальное сальдо:{" "}
            <span className="font-semibold text-ink">
              {formatByn(parseFloat(calendar.data.opening_balance))}
            </span>
            . Не датировано: +{formatByn(parseFloat(calendar.data.not_dated.inflow))} / −
            {formatByn(parseFloat(calendar.data.not_dated.outflow))}.
          </div>
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2.5 font-medium">День</th>
                <th className="px-4 py-2.5 text-right font-medium">Приток</th>
                <th className="px-4 py-2.5 text-right font-medium">Отток</th>
                <th className="px-4 py-2.5 text-right font-medium">Нетто</th>
                <th className="px-4 py-2.5 text-right font-medium">Кумулятив</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((b) => {
                const danger = parseFloat(b.cumulative) < 0;
                return (
                  <tr
                    key={b.bucket_start}
                    className={`border-b border-line last:border-0 ${
                      danger ? "bg-rose-50 dark:bg-rose-900/20" : ""
                    }`}
                  >
                    <td className="px-4 py-2 text-ink">{b.bucket_start}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-emerald-600">
                      {parseFloat(b.inflow) ? `+${formatByn(parseFloat(b.inflow))}` : "—"}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-rose-600">
                      {parseFloat(b.outflow) ? `−${formatByn(parseFloat(b.outflow))}` : "—"}
                    </td>
                    <td
                      className={`px-4 py-2 text-right tabular-nums ${
                        parseFloat(b.net) > 0
                          ? "text-emerald-600"
                          : parseFloat(b.net) < 0
                            ? "text-rose-600"
                            : "text-muted"
                      }`}
                    >
                      {parseFloat(b.net) ? formatByn(parseFloat(b.net)) : "—"}
                    </td>
                    <td
                      className={`px-4 py-2 text-right tabular-nums font-medium ${
                        danger ? "text-rose-700 dark:text-rose-300" : "text-ink"
                      }`}
                    >
                      {formatByn(parseFloat(b.cumulative))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {calendar.data && buckets.length === 0 && (
        <p className="rounded-xl bg-surface p-4 text-sm text-muted shadow-card">
          На горизонте нет ни одного датированного платежа.
        </p>
      )}
    </div>
  );
}

function BankAccountForm({ onCreated }: { onCreated?: () => void }) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [currency, setCurrency] = useState("BYN");
  const [opening, setOpening] = useState("");
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async () => {
    if (!code.trim() || !title.trim()) {
      setError("Код и название обязательны");
      return;
    }
    setPosting(true);
    setError(null);
    try {
      const r = await fetch("/api/finance/bank-accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: code.trim(),
          title: title.trim(),
          currency,
          opening_balance: Number(opening) || 0,
        }),
      });
      if (!r.ok) throw new Error(String(r.status));
      setCode("");
      setTitle("");
      setOpening("");
      setOpen(false);
      onCreated?.();
    } catch {
      setError("Не удалось завести счёт (возможно, код занят)");
    } finally {
      setPosting(false);
    }
  }, [code, title, currency, opening, onCreated]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="ml-auto rounded-md bg-ink/10 px-3 py-1.5 text-sm font-medium text-ink hover:bg-ink/20"
      >
        + Завести счёт
      </button>
    );
  }
  return (
    <div className="flex w-full flex-wrap items-end gap-2 rounded-md bg-sunken p-3">
      <label className="flex flex-col gap-1 text-xs text-muted">
        Код
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="main"
          className="w-28 rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
        />
      </label>
      <label className="flex flex-1 flex-col gap-1 text-xs text-muted">
        Название
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Расчётный счёт BYN"
          className="min-w-[12rem] rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Валюта
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
          className="w-24 rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
        >
          {["BYN", "USD", "EUR", "CNY", "RUB"].map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Сальдо на старте
        <input
          type="number"
          step="0.01"
          value={opening}
          onChange={(e) => setOpening(e.target.value)}
          className="w-32 rounded-md border border-line bg-surface px-2 py-1 text-sm tabular-nums text-ink"
        />
      </label>
      <button
        type="button"
        onClick={submit}
        disabled={posting}
        className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
      >
        {posting ? "…" : "Создать"}
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="rounded-md bg-surface px-3 py-1.5 text-sm text-muted"
      >
        Отмена
      </button>
      {error && <span className="w-full text-xs text-rose-600">{error}</span>}
    </div>
  );
}
