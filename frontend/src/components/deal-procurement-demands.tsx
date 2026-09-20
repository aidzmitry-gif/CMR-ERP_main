"use client";

import { ShoppingCart } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { DealItemFull } from "@/lib/api";
import { createDealDemand, fetchDealDemands, type DealDemand } from "@/lib/procurement-deal-demand";
import { organizations, type Organization } from "@/lib/procurement-machine";

type Props = { dealId: string; items: DealItemFull[] };

function quantity(value: string): string | null {
  const match = /^(0|[1-9]\d*)(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!match || Number(value) <= 0) return null;
  return `${match[1]}.${(match[2] ?? "").padEnd(2, "0")}`;
}

function message(error: unknown) {
  return error instanceof Error ? error.message : "Не удалось создать потребность закупки.";
}

export function DealProcurementDemands({ dealId, items }: Props) {
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [org, setOrg] = useState("");
  const [demands, setDemands] = useState<DealDemand[]>([]);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const keys = useRef(new Map<string, string>());
  const numericDealId = Number(dealId);

  useEffect(() => {
    let active = true;
    void organizations().then((rows) => {
      if (active) setOrgs(rows);
    }).catch((reason: unknown) => {
      if (active) setError(message(reason));
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!org || !Number.isInteger(numericDealId) || numericDealId <= 0) {
      setDemands([]);
      return;
    }
    let active = true;
    setError(null);
    void fetchDealDemands(Number(org), numericDealId).then((rows) => {
      if (active) setDemands(rows);
    }).catch((reason: unknown) => {
      if (active) setError(message(reason));
    });
    return () => { active = false; };
  }, [numericDealId, org]);

  async function create(item: DealItemFull) {
    const requested = quantity(drafts[item.id] ?? String(item.qty));
    if (!requested || Number(requested) > item.qty) {
      setError(`Укажите положительное количество не больше ${item.qty} для «${item.title}».`);
      return;
    }
    if (!org || !Number.isInteger(numericDealId) || numericDealId <= 0) {
      setError("Сначала выберите юрлицо закупки.");
      return;
    }
    const keyId = `${org}:${numericDealId}:${item.id}:${requested}`;
    const key = keys.current.get(keyId) ?? crypto.randomUUID();
    keys.current.set(keyId, key);
    setBusy(item.id);
    setError(null);
    try {
      await createDealDemand(Number(org), numericDealId, item.id, requested, key);
      keys.current.delete(keyId);
      setDemands(await fetchDealDemands(Number(org), numericDealId));
    } catch (reason) {
      // The same key remains in memory: retrying after a network failure cannot create a second demand.
      setError(message(reason));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mt-4 rounded-xl border border-line p-4" aria-label="Потребности закупки">
      <div className="flex items-center gap-2 font-semibold text-ink"><ShoppingCart size={18} className="text-accent-ink" /> Потребности закупки</div>
      <p className="mt-1 text-sm text-muted">Передайте дефицитную позицию в закупки. Это не создаёт резерв на складе или бухгалтерскую проводку.</p>
      <label className="mt-3 block text-sm text-ink">Юрлицо закупки
        <select aria-label="Юрлицо закупки для потребности" value={org} onChange={(event) => setOrg(event.target.value)} disabled={busy !== null} className="ml-2 rounded-lg border border-line bg-surface px-2 py-1 text-sm">
          <option value="">Выберите юрлицо</option>
          {orgs.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.unp}</option>)}
        </select>
      </label>
      {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
      {org && <ul className="mt-3 space-y-2">
        {items.map((item) => {
          const demand = demands.find((row) => row.deal_item_id === item.id);
          return <li key={item.id} className="flex flex-wrap items-center gap-2 rounded-lg bg-sunken px-3 py-2 text-sm">
            <span className="min-w-0 flex-1 truncate">{item.code} · {item.title}</span>
            {demand ? <span className="text-muted">Потребность {demand.qty}; закреплено за заказом {demand.ordered_qty}; осталось обеспечить {demand.free_qty}</span> : <>
              <input aria-label={`Количество в потребность ${item.title}`} type="number" min="0.01" step="0.01" value={drafts[item.id] ?? String(item.qty)} onChange={(event) => setDrafts((previous) => ({ ...previous, [item.id]: event.target.value }))} disabled={busy !== null} className="w-24 rounded-lg border border-line bg-surface px-2 py-1" />
              <span className="text-muted">{item.unit}</span>
              <button type="button" onClick={() => void create(item)} disabled={busy !== null} className="rounded-lg bg-accent px-3 py-1 font-medium text-white disabled:opacity-60">В закупки</button>
            </>}
          </li>;
        })}
        {items.length === 0 && <li className="text-sm text-muted">Добавьте позицию сделки, чтобы передать её в закупки.</li>}
      </ul>}
    </section>
  );
}
