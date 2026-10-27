"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Lot = { lot: string; book_quantity: string | null; book_value_byn: string | null; selectable: boolean; reason: string | null };
export function AccountingLotPicker({ org, date, policyId, account, warehouse, sku, onSelect }: { org: string; date: string; policyId?: number; account: string; warehouse: string; sku: string; onSelect: (lot: string) => void }) {
  const [search,setSearch] = useState(""), [error,setError] = useState("");
  const [lots,setLots] = useState<Lot[] | null>(null), [more,setMore] = useState(false), [busy,setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function load() {
    if (!policyId || !account || busy) return;
    const controller = new AbortController(); pending.current?.abort(); pending.current = controller;
    setBusy(true); setLots(null); setError("");
    try {
      const query = new URLSearchParams({ policy_id: String(policyId), posting_date: date, account, warehouse, sku, search });
      const response = await fetch(`/api/accounting/organizations/${org}/inventory/lots?${query}`, { cache:"no-store", signal:controller.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось проверить партии.");
      if (String(data.organization_id) !== org || data.account !== account || data.warehouse !== warehouse || data.sku !== sku || data.posting_date !== date || data.policy_id !== policyId) throw new Error("Получены остатки другого запроса.");
      if (!controller.signal.aborted) { setLots(data.lots); setMore(data.has_more); }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Партии недоступны."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <div className="min-w-0 space-y-2 rounded border border-line p-2">
    <p className="text-sm">Учтённые партии · {warehouse} · {sku}</p>
    <Input aria-label="Поиск бухгалтерской партии" placeholder="Часть наименования партии" value={search} onChange={event => { pending.current?.abort(); setBusy(false); setLots(null); setSearch(event.target.value); }} />
    <Button variant="secondary" disabled={!policyId || !account || busy} onClick={() => void load()}>Подобрать партию из остатков</Button>
    {busy && <p role="status">Проверяются остатки…</p>}{error && <p role="alert">{error}</p>}
    {lots && <><p className="text-xs text-muted">На {date}. Без резерва; стоимость повторно проверяется при расчёте отгрузки.</p>
      {lots.map(lot => <div key={lot.lot} className="border-t border-line py-2"><Button variant="ghost" disabled={!lot.selectable} onClick={() => onSelect(lot.lot)}>Выбрать партию {lot.lot}</Button><p>{lot.book_quantity ?? "Количество не подтверждено"} · {lot.book_value_byn === null ? "Стоимость не подтверждена" : `${lot.book_value_byn} BYN`}</p>{lot.reason && <p className="text-sm">{lot.reason}</p>}</div>)}
      {!lots.length && <p>Партии не найдены по выбранным счёту, складу и товару.</p>}{more && <p>Показаны первые 100 партий. Уточните поиск.</p>}
    </>}
  </div>;
}
