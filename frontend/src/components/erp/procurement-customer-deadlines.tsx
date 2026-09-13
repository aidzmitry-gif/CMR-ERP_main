"use client";

import { useEffect, useRef, useState } from "react";
import { fetchCustomerDeadlines, type CustomerDeadlines } from "@/lib/procurement-machine";

export function ProcurementCustomerDeadlines({ org, orderId }: { org: number; orderId: number }) {
  return <DeadlineReview key={`${org}:${orderId}`} org={org} orderId={orderId} />;
}

function DeadlineReview({ org, orderId }: { org: number; orderId: number }) {
  const [data, setData] = useState<CustomerDeadlines | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  async function load() {
    const n = ++generation.current; setBusy(true); setData(null); setError("");
    try { const result = await fetchCustomerDeadlines(org, orderId); if (n === generation.current) setData(result); }
    catch (e) { if (n === generation.current) setError(e instanceof Error ? e.message : "Не удалось проверить сроки"); }
    finally { if (n === generation.current) setBusy(false); }
  }
  return <section aria-label="Сроки клиентов по резервам">
    <h3>Сроки клиентов по предварительным резервам</h3>
    <button type="button" disabled={busy} onClick={() => void load()}>{busy ? "Проверка сроков…" : "Проверить клиентские сроки"}</button>
    {error && <p role="alert">{error}</p>}
    {data && <><p>Проверены связанные резервы. Полнота потребностей и штрафы требуют отдельной проверки.</p>
      <p>Самая ранняя дата прихода: {data.earliest_required_arrival ?? "не определена"}. {data.at_risk === true ? "Есть риск опоздания." : data.at_risk === false ? "По указанным срокам опоздания нет." : "Риск не определён."}</p>
      {data.unresolved_deadlines > 0 && <p>Неопределённые сроки: {data.unresolved_deadlines}</p>}
      {data.items.length === 0 && <p>Действующих предварительных резервов нет.</p>}
      {data.items.map(x => <p key={x.reservation_id}>Сделка #{x.deal_id}: {x.sku_code}, {x.outstanding_qty}; срок клиента: {x.ship_deadline || "не указан"}; приход до: {x.required_arrival ?? "не определён"}</p>)}
    </>}
  </section>;
}
