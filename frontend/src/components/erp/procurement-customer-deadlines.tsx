"use client";

import { useEffect, useRef, useState } from "react";
import { fetchCustomerDeadlines, type CustomerDeadlines } from "@/lib/procurement-machine";

type Props = { org: number; orderId: number; onUseDate?: (date: string) => void; disabled?: boolean };
export function ProcurementCustomerDeadlines({ org, orderId, onUseDate, disabled }: Props) {
  return <DeadlineReview key={`${org}:${orderId}`} org={org} orderId={orderId} onUseDate={onUseDate} disabled={disabled} />;
}

function DeadlineReview({ org, orderId, onUseDate, disabled }: Props) {
  const [data, setData] = useState<CustomerDeadlines | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  async function load(useDate = false) {
    const n = ++generation.current; setBusy(true); setData(null); setError("");
    try { const result = await fetchCustomerDeadlines(org, orderId); if (n === generation.current) { setData(result); if (useDate && result.earliest_required_arrival && result.unresolved_deadlines === 0) onUseDate?.(result.earliest_required_arrival); } }
    catch (e) { if (n === generation.current) setError(e instanceof Error ? e.message : "Не удалось проверить сроки"); }
    finally { if (n === generation.current) setBusy(false); }
  }
  return <section aria-label="Сроки клиентов по резервам">
    <h3>Сроки клиентов по предварительным резервам</h3>
    <button type="button" disabled={busy} onClick={() => void load()}>{busy ? "Проверка сроков…" : "Проверить клиентские сроки"}</button>
    {error && <p role="alert">{error}</p>}
    {data && <><p>{data.risk_details
      ? "Проверены связанные резервы. Полнота потребностей требует отдельной проверки. Условия штрафов показаны по текущим данным связанных сделок; сумма штрафа не рассчитана."
      : "Проверены связанные резервы. Полнота потребностей и штрафы требуют отдельной проверки."}</p>
      <p>Самая ранняя дата прихода: {data.earliest_required_arrival ?? "не определена"}. {data.at_risk === true ? "Есть риск опоздания." : data.at_risk === false ? "По указанным срокам опоздания нет." : "Риск не определён."}</p>
      {data.risk_details && <>
        <p>{data.risk_details.slack_days === null ? "Запас по сроку не определён."
          : data.risk_details.slack_days < 0 ? `Опоздание к требуемой дате прихода: ${-data.risk_details.slack_days} дн.`
            : `Запас до требуемой даты прихода: ${data.risk_details.slack_days} дн.`}</p>
        {data.risk_details.schedule_start_in_past && <p>Плановое начало маршрута уже в прошлом.</p>}
      </>}
      {data.unresolved_deadlines > 0 && <p>Неопределённые сроки: {data.unresolved_deadlines}</p>}
      {onUseDate && <button type="button" disabled={busy || disabled || !data.earliest_required_arrival || data.unresolved_deadlines > 0} onClick={() => void load(true)}>Обновить сроки и подставить дату в план</button>}
      {data.items.length === 0 && <p>Действующих предварительных резервов нет.</p>}
      {data.items.map(x => {
        const terms = data.risk_details?.items.find(row => row.reservation_id === x.reservation_id);
        return <div key={x.reservation_id}>
          <p>Сделка {terms?.number || `#${x.deal_id}`}: {x.sku_code}, {x.outstanding_qty}; срок клиента: {x.ship_deadline || "не указан"}; приход до: {x.required_arrival ?? "не определён"}</p>
          {terms && <p>Условия штрафа из сделки: ставка {terms.penalty_rate_pct === null ? "не указана" : `${terms.penalty_rate_pct}%`}; предел {terms.penalty_cap_pct === null ? "не указан" : `${terms.penalty_cap_pct}%`}. {terms.penalty_terms || "Текст условий не указан."}</p>}
        </div>;
      })}
    </>}
  </section>;
}
