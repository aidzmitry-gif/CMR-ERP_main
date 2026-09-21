"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";

type Organization = { id: number; name: string; unp: string };
type Identity = { organization_id: number; principal: string; can_manage: boolean };
type RequestRow = {
  id: number;
  number: string;
  supplier: string;
  item: string;
  quantity: string;
  planned_amount: string;
  due_date: string | null;
  stage: string;
};
type OrderRow = {
  id: number;
  number: string;
  supplier: string;
  status: string;
  eta_date: string | null;
  freight_byn: string;
};
type Page<T> = { organization_id: number; items: T[]; next_after_id: number | null };
type Chain = {
  organization_id: number;
  order: { id: number };
  request_links: { request_id: number }[];
  status: "complete" | "partial";
  blockers: string[];
};
type ChainState = { state: "ready"; complete: boolean; requestIds: number[]; blockers: string[] } | { state: "unavailable" };
type StageId = "need" | "sourcing" | "nego" | "analysis" | "approval" | "po" | "supply" | "qc" | "done";
type Card = {
  id: string;
  stage: StageId;
  title: string;
  subtitle: string;
  meta: string;
  href: string;
  action?: { requestId: number; stage: "need" | "sourcing" | "nego" | "analysis" };
  note?: string;
};

const prefix = (org: number) => `/api/procurement/organizations/${org}`;
const requestStages: StageId[] = ["need", "sourcing", "nego", "analysis", "approval"];
const stageTitles: Record<StageId, string> = {
  need: "Потребность",
  sourcing: "Поиск поставщика",
  nego: "Переговоры",
  analysis: "Анализ",
  approval: "Согласование",
  po: "Заказ поставщику",
  supply: "Поставка",
  qc: "Приёмка",
  done: "Завершено",
};
const nextRequestStage: Record<"need" | "sourcing" | "nego" | "analysis", "sourcing" | "nego" | "analysis" | "approval"> = {
  need: "sourcing",
  sourcing: "nego",
  nego: "analysis",
  analysis: "approval",
};

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Не удалось проверить закупки";
}

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: "no-store", ...options });
  const body = await response.text();
  if (!response.ok) throw new Error(`Ошибка ${response.status}: ${body || "без описания"}`);
  if (!body) throw new Error("Сервис закупок вернул пустой ответ");
  try {
    return JSON.parse(body) as T;
  } catch {
    throw new Error("Сервис закупок вернул некорректный ответ");
  }
}

function organizationHint(value: string | undefined) {
  return value && /^[1-9]\d*$/.test(value) && Number(value) <= 2147483647 ? value : undefined;
}

function validPage<T>(value: Page<T>, org: number, after: number) {
  return value.organization_id === org && Array.isArray(value.items)
    && (value.next_after_id === null || (Number.isInteger(value.next_after_id) && value.next_after_id > after));
}

function orderStage(order: OrderRow, chain: ChainState | undefined): { stage: StageId; note?: string } | null {
  if (order.status === "cancelled") return null;
  if (order.status === "draft") return { stage: "po" };
  if (["ordered", "shipped", "customs"].includes(order.status)) return { stage: "supply", note: `Статус заказа: ${order.status}` };
  if (order.status === "received") {
    if (chain?.state === "ready" && chain.complete) return { stage: "done" };
    if (chain?.state === "ready") return { stage: "qc", note: chain.blockers.length ? `Не завершено: ${chain.blockers.join(", ")}` : "Нужна проверка первичных документов и приёмки" };
    return { stage: "qc", note: "Цепочка первичных документов пока не подтверждена" };
  }
  return { stage: "po", note: `Неизвестный статус заказа: ${order.status}` };
}

function cardsFor(org: number, requests: RequestRow[], orders: OrderRow[], chains: Record<number, ChainState>): { cards: Card[]; cancelled: number } {
  const linkedRequests = new Set<number>();
  for (const chain of Object.values(chains)) {
    if (chain.state === "ready") chain.requestIds.forEach(id => linkedRequests.add(id));
  }
  const cards: Card[] = [];
  for (const request of requests) {
    if (!requestStages.includes(request.stage as StageId) && request.stage !== "po") continue;
    if (request.stage === "po" && linkedRequests.has(request.id)) continue;
    const stage = request.stage === "po" ? "po" : request.stage as StageId;
    const action = request.stage in nextRequestStage
      ? { requestId: request.id, stage: request.stage as "need" | "sourcing" | "nego" | "analysis" }
      : undefined;
    cards.push({
      id: `request:${request.id}`,
      stage,
      title: request.number || `Заявка #${request.id}`,
      subtitle: request.item,
      meta: `${request.supplier || "Поставщик не указан"} · ${request.quantity} шт. · ${request.planned_amount}`,
      href: stage === "approval" ? `/erp/procurement/orders?org=${org}&request=${request.id}` : `/erp/procurement/planning?org=${org}`,
      action,
      note: request.due_date ? `Плановая дата: ${request.due_date}` : undefined,
    });
  }
  for (const order of orders) {
    const placement = orderStage(order, chains[order.id]);
    if (!placement) continue;
    cards.push({
      id: `order:${order.id}`,
      stage: placement.stage,
      title: order.number || `Заказ #${order.id}`,
      subtitle: order.supplier || "Поставщик не указан",
      meta: order.eta_date ? `ETA: ${order.eta_date}` : "Дата поставки не задана",
      href: `/erp/procurement/orders/${order.id}?org=${org}`,
      note: placement.note,
    });
  }
  return { cards, cancelled: orders.filter(order => order.status === "cancelled").length };
}

export function ProcurementKanban({ suggestedOrg }: { suggestedOrg?: string }) {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [organization, setOrganization] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void api<Organization[]>("/api/procurement/receipt-organizations").then(rows => {
      if (!active) return;
      setOrganizations(rows);
      const hint = organizationHint(suggestedOrg);
      if (hint && rows.some(row => String(row.id) === hint)) setOrganization(hint);
    }).catch(reason => { if (active) setError(errorText(reason)); });
    return () => { active = false; };
  }, [suggestedOrg]);
  return <section className="space-y-4 p-6">
    <div className="space-y-1"><h1 className="text-xl font-semibold">Воронка закупок</h1><p>Канбан показывает только документы выбранного юрлица. Этапы поставки и приёмки строятся из фактического статуса заказа и цепочки первичных документов.</p></div>
    {error && <p role="alert">{error}</p>}
    <Select aria-label="Юрлицо канбана закупок" value={organization} onChange={event => setOrganization(event.target.value)}><option value="">Выберите юрлицо</option>{organizations.map(row => <option key={row.id} value={row.id}>{row.name} · {row.unp}</option>)}</Select>
    {organization && <CompanyKanban key={organization} org={Number(organization)} />}
  </section>;
}

function CompanyKanban({ org }: { org: number }) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [requestNext, setRequestNext] = useState<number | null>(null);
  const [orderNext, setOrderNext] = useState<number | null>(null);
  const [chains, setChains] = useState<Record<number, ChainState>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const active = (token: number) => generation.current === token;

  async function page<T extends RequestRow | OrderRow>(kind: "request" | "order", after = 0) {
    const result = await api<Page<T>>(`${prefix(org)}/owned-sources?kind=${kind}&after_id=${after}`);
    if (!validPage(result, org, after)) throw new Error("Сервис закупок вернул некорректную страницу документов");
    return result;
  }

  async function inspectChains(rows: OrderRow[], token: number, reset: boolean) {
    const results = await Promise.all(rows.map(async order => {
      try {
        const value = await api<Chain>(`${prefix(org)}/orders/${order.id}/chain`);
        if (value.organization_id !== org || value.order?.id !== order.id || !Array.isArray(value.request_links) || !["complete", "partial"].includes(value.status) || !Array.isArray(value.blockers)) throw new Error("Некорректная цепочка заказа");
        return [order.id, { state: "ready", complete: value.status === "complete", requestIds: value.request_links.map(link => link.request_id).filter(Number.isInteger), blockers: value.blockers }] as const;
      } catch {
        return [order.id, { state: "unavailable" }] as const;
      }
    }));
    if (!active(token)) return;
    setChains(previous => reset ? Object.fromEntries(results) : { ...previous, ...Object.fromEntries(results) });
  }

  async function refresh(token: number) {
    const [who, requestPage, orderPage] = await Promise.all([
      api<Identity>(`${prefix(org)}/request-plan-context`),
      page<RequestRow>("request"),
      page<OrderRow>("order"),
    ]);
    if (!active(token)) return;
    if (who.organization_id !== org || !who.principal || typeof who.can_manage !== "boolean") throw new Error("Пользователь или юрлицо не подтверждены");
    setIdentity(who); setRequests(requestPage.items); setOrders(orderPage.items); setRequestNext(requestPage.next_after_id); setOrderNext(orderPage.next_after_id);
    await inspectChains(orderPage.items, token, true);
  }

  useEffect(() => {
    const token = ++generation.current;
    void refresh(token).catch(reason => { if (active(token)) setError(errorText(reason)); }).finally(() => { if (active(token)) setBusy(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => { generation.current++; };
    // The keyed component owns a fixed organization; generation rejects stale results.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function run(action: (token: number) => Promise<void>) {
    if (busy) return;
    const token = ++generation.current;
    setBusy(true); setError(""); setNotice("");
    void action(token).catch(reason => { if (active(token)) setError(errorText(reason)); }).finally(() => { if (active(token)) setBusy(false); });
  }

  function loadMore(kind: "request" | "order", after: number) {
    run(async token => {
      const next = kind === "request" ? await page<RequestRow>(kind, after) : await page<OrderRow>(kind, after);
      if (!active(token)) return;
      if (kind === "request") {
        setRequests(rows => [...rows, ...next.items.filter(row => !rows.some(existing => existing.id === row.id))] as RequestRow[]);
        setRequestNext(next.next_after_id);
      } else {
        const incoming = next.items as OrderRow[];
        setOrders(rows => [...rows, ...incoming.filter(row => !rows.some(existing => existing.id === row.id))]);
        setOrderNext(next.next_after_id);
        await inspectChains(incoming, token, false);
      }
    });
  }

  function advance(card: NonNullable<Card["action"]>) {
    run(async token => {
      if (!identity?.can_manage) return;
      const current = await api<Identity>(`${prefix(org)}/request-plan-context`);
      if (current.organization_id !== org || current.principal !== identity.principal || !current.can_manage) throw new Error("Права или пользователь изменились. Обновите канбан.");
      await api(`${prefix(org)}/requests/${card.requestId}/stage`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-Expected-Principal": identity.principal },
        body: JSON.stringify({ expected_stage: card.stage, stage: nextRequestStage[card.stage] }),
      });
      if (!active(token)) return;
      await refresh(token);
      if (active(token)) setNotice("Стадия заявки обновлена.");
    });
  }

  const { cards, cancelled } = cardsFor(org, requests, orders, chains);
  return <div className="space-y-4">
    {!identity && !error && <p role="status">Загрузка документов закупок…</p>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {identity && !identity.can_manage && <p>Доступен просмотр. Перевод заявки между этапами доступен главному бухгалтеру этого юрлица с доступом к закупкам.</p>}
    <div className="flex flex-wrap gap-3"><Button disabled={busy || !identity} variant="secondary" onClick={() => run(refresh)}>Обновить канбан</Button><Link className="self-center text-accent underline" href={`/erp/procurement/planning?org=${org}`}>Открыть план закупок</Link><Link className="self-center text-accent underline" href={`/erp/procurement/receipts?org=${org}`}>Открыть накладные на поступление</Link></div>
    <div className="grid auto-cols-[minmax(252px,1fr)] grid-flow-col gap-3 overflow-x-auto pb-3" aria-label="Канбан закупок">
      {(Object.keys(stageTitles) as StageId[]).map(stage => <section key={stage} aria-label={`Колонка ${stageTitles[stage]}`} className="min-h-[250px] space-y-3 rounded-xl border border-line bg-sunken/40 p-3"><header className="flex items-center justify-between gap-2"><h2 className="font-semibold">{stageTitles[stage]}</h2><span className="rounded-full bg-surface px-2 py-0.5 text-xs text-muted">{cards.filter(card => card.stage === stage).length}</span></header>
        {cards.filter(card => card.stage === stage).map(card => <article key={card.id} className="space-y-2 rounded-lg border border-line bg-surface p-3 shadow-sm"><Link className="block font-medium text-accent underline" href={card.href}>{card.title}</Link><p className="text-sm">{card.subtitle}</p><p className="text-xs text-muted">{card.meta}</p>{card.note && <p className="text-xs text-muted">{card.note}</p>}{card.action && <Button size="sm" disabled={busy || !identity?.can_manage} onClick={() => advance(card.action!)}>Далее: {stageTitles[nextRequestStage[card.action.stage]]}</Button>}</article>)}
        {!cards.some(card => card.stage === stage) && <p className="text-sm text-muted">Нет документов на этом этапе.</p>}
      </section>)}
    </div>
    {(requestNext !== null || orderNext !== null) && <div className="flex flex-wrap gap-3"><p className="self-center text-sm text-muted">Показана первая страница документов; незагруженные строки не считаются пустыми этапами.</p>{requestNext !== null && <Button disabled={busy} variant="secondary" onClick={() => loadMore("request", requestNext)}>Загрузить ещё заявки</Button>}{orderNext !== null && <Button disabled={busy} variant="secondary" onClick={() => loadMore("order", orderNext)}>Загрузить ещё заказы</Button>}</div>}
    {cancelled > 0 && <p className="text-sm text-muted">Отменённых заказов вне канбана: {cancelled}. Их можно проверить в разделе заказов поставщикам.</p>}
  </div>;
}
