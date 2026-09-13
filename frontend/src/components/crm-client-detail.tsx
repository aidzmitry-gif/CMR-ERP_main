"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { DealContacts } from "@/components/deal-contacts";
import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import { createDeal } from "@/lib/api";

type Client = { id: number; name: string; owner_id: number; unp: string | null; source: "crm" };
type LinkedDeal = { id: number; number: string; title: string };

export function CrmClientDetail({ clientId }: { clientId: number }) {
  const [revision, setRevision] = useState(0);
  const [creating, setCreating] = useState(false);
  const generation = useRef(0);
  useLayoutEffect(() => () => { generation.current += 1; }, [clientId]);
  const [loaded, setLoaded] = useState<{ clientId: number; revision: number; client?: Client; deals?: LinkedDeal[]; error?: string } | null>(null);
  const state = loaded?.clientId === clientId && loaded.revision === revision ? loaded : null;
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    void (async () => {
      try {
        const responses = await Promise.all(["", "/deals"].map((suffix) => fetch(`/api/sales/clients/${clientId}${suffix}`, {
          cache: "no-store", signal: controller.signal,
        })));
        if (responses.some((response) => !response.ok)) throw new Error(responses.some((response) => response.status === 403 || response.status === 404)
          ? "Клиент недоступен." : "Не удалось загрузить клиента. Повторите попытку.");
        const [client, deals] = await Promise.all(responses.map((response) => response.json()));
        if (client?.id !== clientId || client.source !== "crm" || typeof client.name !== "string"
          || (client.unp !== null && typeof client.unp !== "string")
          || !Number.isSafeInteger(client.owner_id) || client.owner_id <= 0
          || !Array.isArray(deals) || !deals.every((deal) => deal && Number.isSafeInteger(deal.id) && deal.id > 0 && typeof deal.number === "string" && typeof deal.title === "string")) {
          throw new Error("Сервер вернул некорректные данные клиента.");
        }
        if (current) setLoaded({ clientId, revision, client, deals });
      } catch (error) {
        if (current) setLoaded({ clientId, revision, error: error instanceof Error ? error.message : "Ошибка загрузки клиента." });
      }
    })();
    return () => { current = false; controller.abort(); };
  }, [clientId, revision]);

  return <section className="space-y-4 p-4 md:p-6" aria-label="Карточка клиента">
    <Link href="/crm/clients" className="text-sm underline">К списку клиентов</Link>
    {!state && <p role="status">Загрузка клиента…</p>}
    {state?.error && <div role="alert"><p>{state.error}</p><button type="button" className="underline" onClick={() => setRevision((value) => value + 1)}>Повторить</button></div>}
    {state?.client && <>
      <h1 className="text-xl font-semibold">{state.client.name}</h1>
      <p className="text-sm text-muted">УНП: {state.client.unp ?? "Не указан"}</p>
      <DealContacts key={`contacts:${clientId}`} clientId={clientId} />
      <div className="space-y-3 rounded-xl border border-line p-4">
        <h2 className="font-semibold">Сделки клиента</h2>
        <button type="button" className="rounded-lg bg-accent px-4 py-2 text-white" onClick={() => { generation.current += 1; setCreating(true); }}>Новая сделка клиента</button>
        {state.deals?.length ? <ul className="space-y-2">{state.deals.map((deal) => <li key={deal.id}>
          <Link className="underline" href={`/crm/deals/${deal.id}`}>{deal.number} — {deal.title}</Link>
        </li>)}</ul> : <p className="text-sm text-muted">Сделок пока нет.</p>}
      </div>
      {creating && <CreateDealModal key={`deal:${clientId}`} client={state.client} stages={[]} defaultStage="new" onClose={() => { generation.current += 1; setCreating(false); }} onCreate={async (input) => {
        const operation = ++generation.current;
        const deal = await createDeal(input);
        if (operation !== generation.current) return false;
        if (!deal) return false;
        setCreating(false);
        setRevision((value) => value + 1);
        return true;
      }} />}
    </>}
  </section>;
}
