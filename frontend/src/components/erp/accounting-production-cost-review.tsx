"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { sameOverheadCommand, type CostReviewCommand } from "@/lib/production-overhead-journal";
import type { PreparedOverhead } from "./accounting-production-overhead-confirmation";
type SourceLine = { line_id: number; entry_id: number; source: string; account: string; side: string;
  amount_byn: string; dimensions: Record<string, string>; posting_date: string; opening: boolean };
export type CostSource = { digest: string; snapshot: { organization_id: number; month: string; policy_id: number;
  basis?: string; settings?: { wip_account: string; overhead_accounts: string[]; order_dimension: string }; lines: SourceLine[] } };
type Order = { id: number; number: string; product: string };
type Review = { digest: string; snapshot: { organization_id: number; month: string; status: string; posted: boolean;
  review: CostReviewCommand;
  allocations: { account: string; pool_dimensions: Record<string, string>; allocation: {
    amount_byn: string; shares: { order_id: number; basis_amount: string; amount_byn: string }[] } }[] } };
export function AccountingProductionCostReview({ source, disabled, onPrepared, correctionOf }: { source: CostSource; disabled: boolean; onPrepared?: (value: PreparedOverhead | null) => void; correctionOf?: number }) {
  const s = source.snapshot, settings = s.settings;
  const [orders, setOrders] = useState<Order[] | null>(null), [roles, setRoles] = useState<Record<number, string>>({});
  const [reasons, setReasons] = useState<Record<number, string>>({}), [bindings, setBindings] = useState<Record<string, string>>({});
  const [bindingReasons, setBindingReasons] = useState<Record<string, string>>({});
  const [review, setReview] = useState<Review | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const analytical = [...new Set(s.lines.filter(line => roles[line.line_id] === "direct_cost")
    .map(line => line.dimensions[settings?.order_dimension ?? "order"]))].sort();
  const ready = (analytical.length > 0 ? !!orders : !!correctionOf) && s.lines.length > 0 && s.lines.every(line => roles[line.line_id] && reasons[line.line_id]?.trim().length >= 10)
    && analytical.every(key => orders?.some(order => String(order.id) === bindings[key]) && bindingReasons[key]?.trim().length >= 10)
    && new Set(analytical.map(key => bindings[key])).size === analytical.length;
  function edited(action: () => void) { setReview(null); onPrepared?.(null); action(); }
  async function requestPreview(calculate: boolean) {
    if (disabled || controller.current || (calculate && !ready)) return;
    const pending = new AbortController(); controller.current = pending; setBusy(true); setError(""); setReview(null);
    onPrepared?.(null);
    if (!calculate) setOrders(null);
    try {
      const command: CostReviewCommand = { policy_id: s.policy_id, expected_source_digest: source.digest,
        classifications: s.lines.map(line => ({ line_id: line.line_id, role: roles[line.line_id] as CostReviewCommand["classifications"][number]["role"], evidence: reasons[line.line_id]?.trim() ?? "" })),
        orders: analytical.map(key => ({ analytical_order: key, order_id: Number(bindings[key]), evidence: bindingReasons[key]?.trim() ?? "" })) };
      const reviewPath = correctionOf ? `production-overhead-correction-review?original_entry_id=${correctionOf}` : "production-cost-review";
      const response = await fetch(calculate ? `/api/accounting/organizations/${s.organization_id}/periods/${s.month}/${reviewPath}`
        : `/api/production/organizations/${s.organization_id}/orders`, { cache: "no-store", signal: pending.signal,
        ...(calculate ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(command) } : {}) });
      if (!response.ok) throw new Error(calculate ? "Расчёт не подтверждён. Проверьте состав затрат, наряды и актуальность источников." : "Не удалось загрузить наряды выбранного юрлица.");
      const data = await response.json();
      if (pending.signal.aborted) return;
      if (calculate) {
        const result = data as Review;
        if (!/^[a-f0-9]{64}$/.test(result.digest) || result.snapshot?.organization_id !== s.organization_id || result.snapshot.month !== s.month
          || result.snapshot.status !== "reviewed_allocation_preview" || result.snapshot.posted !== false || !Array.isArray(result.snapshot.allocations)
          || !sameOverheadCommand(result.snapshot.review, command)
          || result.snapshot.allocations.some(pool => typeof pool.allocation?.amount_byn !== "string" || !/^\d+\.\d{2}$/.test(pool.allocation.amount_byn)
            || !Array.isArray(pool.allocation.shares) || pool.allocation.shares.some(share => !orders?.some(order => order.id === share.order_id)
              || typeof share.amount_byn !== "string" || !/^\d+\.\d{2}$/.test(share.amount_byn)))) throw new Error("Полученный расчёт не соответствует выбранным данным.");
        setReview(result);
        onPrepared?.({ review: command, digest: result.digest,
          earliestDate: s.lines.filter(line => roles[line.line_id] !== "excluded").map(line => line.posting_date).sort().slice(-1)[0] ?? `${s.month}-01` });
      } else {
        if (!Array.isArray(data) || data.some(order => !Number.isSafeInteger(order.id) || order.id <= 0 || typeof order.number !== "string" || typeof order.product !== "string"))
          throw new Error("Получен некорректный список производственных нарядов.");
        setOrders(data);
      }
    } catch (e) { if (!pending.signal.aborted) setError((e as Error).message); }
    finally { if (!pending.signal.aborted) { controller.current = null; setBusy(false); } }
  }
  if (!settings || s.basis !== "direct_cost") return <p>Проверка базы по трудозатратам и объёму выпуска требует соответствующих регистров. Этот экран рассчитывает распределение по прямым затратам.</p>;
  return <fieldset className="min-w-0 space-y-3 rounded border border-line p-2" disabled={disabled || busy}>
    <legend>Проверка состава производственных затрат</legend>
    <p>Укажите назначение каждой строки. Начальные остатки и прошлые месяцы исключаются из базы текущего месяца с объяснением.</p>
    <Button onClick={() => void requestPreview(false)}>Загрузить производственные наряды</Button>
    {s.lines.map(line => <article key={line.line_id} className="space-y-2 border-b border-line pb-3">
      <p>Проводка №{line.entry_id} · {line.source} · {line.posting_date} · {line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.amount_byn} BYN</p>
      <p>{Object.entries(line.dimensions).map(([key, value]) => `${key === "department" ? "Подразделение" : key === "order" ? "Заказ" : key}: ${value}`).join(' · ')}</p>
      <Select aria-label={`Назначение строки ${line.line_id}`} value={roles[line.line_id] ?? ""} onChange={e => edited(() => setRoles({ ...roles, [line.line_id]: e.target.value }))}>
        <option value="">Выберите назначение</option><option value="excluded">Исключить из распределения</option>
        {!line.opening && line.posting_date.startsWith(s.month) && <>
          {line.account === settings.wip_account && <option value="direct_cost">Прямые затраты (база)</option>}
          {settings.overhead_accounts.includes(line.account) && <option value="overhead">Накладные расходы к распределению</option>}
        </>}
      </Select>
      <Input aria-label={`Основание строки ${line.line_id}`} maxLength={1000} placeholder="Почему строка включена или исключена" value={reasons[line.line_id] ?? ""} onChange={e => edited(() => setReasons({ ...reasons, [line.line_id]: e.target.value }))} />
    </article>)}
    {analytical.map(key => <div className="space-y-2" key={key}><p>Заказ в бухгалтерской аналитике: {key}</p>
      <Select aria-label={`Наряд для заказа ${key}`} value={bindings[key] ?? ""} onChange={e => edited(() => setBindings({ ...bindings, [key]: e.target.value }))}>
        <option value="">Выберите производственный наряд</option>{orders?.map(order => <option key={order.id} value={order.id}>{order.number} · {order.product}</option>)}
      </Select>
      <Input aria-label={`Основание связи заказа ${key}`} maxLength={1000} value={bindingReasons[key] ?? ""} placeholder="Документ, подтверждающий связь с нарядом" onChange={e => edited(() => setBindingReasons({ ...bindingReasons, [key]: e.target.value }))} />
    </div>)}
    <Button disabled={!ready} onClick={() => void requestPreview(true)}>Рассчитать распределение по проверенным строкам</Button>
    {error && <p role="alert">{error}</p>}
    {review && <div role="status"><p>{correctionOf ? "Целевое распределение после пересчёта. Исправление ещё не проведено." : "Предварительное распределение. Проводки ещё не созданы."}</p>{correctionOf && review.snapshot.allocations.length === 0 && <p>Целевое распределение равно нулю. Расчёт исправления покажет снятие ранее распределённых сумм.</p>}{review.snapshot.allocations.map((pool, i) => <div key={i}>
      <p>Кт {pool.account} · {Object.entries(pool.pool_dimensions).map(([key, value]) => `${key === "department" ? "Подразделение" : key}: ${value}`).join(' · ')} · {pool.allocation.amount_byn} BYN</p>
      {pool.allocation.shares.map(share => <p key={share.order_id}>Дт {settings.wip_account} · {orders?.find(order => order.id === share.order_id)?.number} · заказ в аналитике: {review.snapshot.review.orders.find(order => order.order_id === share.order_id)?.analytical_order} · база {share.basis_amount} · распределено {share.amount_byn} BYN</p>)}
    </div>)}</div>}
  </fieldset>;
}
