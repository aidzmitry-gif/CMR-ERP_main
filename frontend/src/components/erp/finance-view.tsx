"use client";

import { useCallback, useEffect, useState } from "react";

import { SourceTag } from "@/components/source-tag";
import { formatByn } from "@/lib/format";

// ──────────────────────────── Контракты ответов /finance/* ────────────────────────────

interface FinanceSummary {
  currency: string;
  margin: { revenue: number; landed: number; freight: number; gross: number; pct: number | null };
  cash: {
    inflow: number;
    outflow: number;
    net: number;
    received: number;
    pending_receivable: number;
    freight_refund: number;
  };
  costs: { kind: string; label: string; amount: number }[];
}

interface Payment {
  id: number;
  ref: string;
  amount: number;
  status: string;
  kind: string;
  due_date: string | null;
  paid_at: string | null;
  deal_id: number | null;
  counterparty_ref: string | null;
  outstanding: number | null;
  is_overdue: boolean | null;
}

interface AgingSide {
  buckets: Record<string, number>;
  total: number;
}
interface AgingResp {
  as_of: string;
  currency: string;
  ar: AgingSide;
  ap: AgingSide;
}

interface CashflowWeek {
  week_start: string;
  inflow: number;
  outflow: number;
  net: number;
  cumulative: number;
}
interface CashflowResp {
  as_of: string;
  currency: string;
  opening_balance: number;
  weeks: CashflowWeek[];
  not_dated: { inflow: number; outflow: number };
}

interface MarginRow {
  key: number | string | null;
  revenue: number;
  landed: number;
  freight: number;
  gross: number;
  pct: number | null;
}
interface MarginResp {
  currency: string;
  items: MarginRow[];
}

interface ReconResp {
  as_of: string;
  source: string;
  source_available: boolean;
  matched: { ref: string; amount: number; counterparty_ref: string | null }[];
  only_in_erp: { ref: string; amount: number; counterparty_ref: string | null }[];
  only_in_1c: { ref: string | null; amount: number; counterparty_ref: string | null }[];
}

// ──────────────────────────── Подсобки ────────────────────────────

const KIND_LABEL: Record<string, string> = {
  receivable: "Счёт к получению",
  freight: "Фрахт",
  freight_refund: "Возврат фрахта",
  landed: "Себестоимость",
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
  return p.kind === "receivable" ? p.amount >= 0 : p.amount < 0;
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

type TabId = "summary" | "payments" | "aging" | "cashflow" | "margin" | "reconcile";
const TABS: { id: TabId; label: string }[] = [
  { id: "summary", label: "Касса и маржа" },
  { id: "payments", label: "Платежи" },
  { id: "aging", label: "Aging" },
  { id: "cashflow", label: "Cash-flow" },
  { id: "margin", label: "Маржа" },
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
        {tab === "margin" && <MarginTab />}
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
        <Card title="Поступления" value={formatByn(s.cash.inflow)} tone="pos" />
        <Card title="Расходы" value={formatByn(s.cash.outflow)} tone="neg" />
        <Card
          title="Сальдо"
          value={formatByn(s.cash.net)}
          tone={s.cash.net >= 0 ? "pos" : "neg"}
        />
        <Card title="К поступлению (счета)" value={formatByn(s.cash.pending_receivable)} />
      </div>

      {/* Фактическая маржа */}
      <h2 className="mt-6 text-sm font-semibold text-muted">Фактическая маржа (по фактам)</h2>
      <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card title="Выручка" value={formatByn(s.margin.revenue)} />
        <Card title="Себестоимость (landed)" value={formatByn(s.margin.landed)} />
        <Card title="Фрахт (нетто)" value={formatByn(s.margin.freight)} />
        <Card
          title={`Валовая прибыль${s.margin.pct != null ? ` · ${s.margin.pct.toFixed(1)}%` : ""}`}
          value={formatByn(s.margin.gross)}
          tone={s.margin.gross >= 0 ? "pos" : "neg"}
        />
      </div>
      {s.margin.revenue === 0 && (
        <p className="mt-2 text-xs text-muted">
          Выручки по фактам пока нет — маржа появится после первых проведённых счетов.
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
                  {formatByn(c.amount)}
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
                  {formatByn(Math.abs(p.amount))}
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
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatByn(p.amount)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                  {p.outstanding != null ? formatByn(p.outstanding) : "—"}
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
      empty={!loading && !error && data != null && data.ar.total === 0 && data.ap.total === 0}
      what="aging"
    />
  );
  if (loading || error || !data || (data.ar.total === 0 && data.ap.total === 0)) return bar;
  const isAccent = (b: string) => b === "61-90" || b === "90+";
  const Side = ({ title, side }: { title: string; side: AgingSide }) => (
    <div className="overflow-hidden rounded-xl bg-surface shadow-card">
      <div className="border-b border-line px-4 py-2.5 text-sm font-semibold text-ink">
        {title} · {formatByn(side.total)}
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
                {formatByn(side.buckets[b] ?? 0)}
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
  const bar = <State loading={loading} error={error} empty={!loading && !error && data?.weeks.every((w) => w.inflow === 0 && w.outflow === 0)} what="прогноз кэш-фло" />;
  if (loading || error || !data) return bar;
  const max = Math.max(
    1,
    ...data.weeks.map((w) => Math.max(w.inflow, w.outflow)),
  );
  return (
    <>
      <p className="text-xs text-muted">
        На {data.as_of}. Начальное сальдо: {formatByn(data.opening_balance)}. Не датировано:
        +{formatByn(data.not_dated.inflow)} / −{formatByn(data.not_dated.outflow)}.
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
              const inW = `${(w.inflow / max) * 50}%`;
              const outW = `${(w.outflow / max) * 50}%`;
              return (
                <tr key={w.week_start} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 text-ink">{w.week_start}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-emerald-600">
                    +{formatByn(w.inflow)}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-rose-600">
                    −{formatByn(w.outflow)}
                  </td>
                  <td
                    className={`px-4 py-2.5 text-right tabular-nums ${
                      w.net >= 0 ? "text-emerald-600" : "text-rose-600"
                    }`}
                  >
                    {formatByn(w.net)}
                  </td>
                  <td
                    className={`px-4 py-2.5 text-right tabular-nums ${
                      w.cumulative >= 0 ? "text-ink" : "text-rose-600"
                    }`}
                  >
                    {formatByn(w.cumulative)}
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
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatByn(row.revenue)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">{formatByn(row.landed)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">{formatByn(row.freight)}</td>
                <td
                  className={`px-4 py-2.5 text-right tabular-nums ${
                    row.gross >= 0 ? "text-emerald-600" : "text-rose-600"
                  }`}
                >
                  {formatByn(row.gross)}
                </td>
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
      <Section title="Маржа по сделкам" resp={byDeal} keyLabel="Сделка" />
      <Section title="Маржа по контрагентам" resp={byCp} keyLabel="Контрагент (УНП)" isCounterparty />
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
    rows: { ref: string | null; amount: number; counterparty_ref: string | null }[];
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
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatByn(r.amount)}</td>
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
