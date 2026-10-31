"use client";

import { InstanceOrganizationGate } from "@/components/instance-organization-gate";

import { Button } from "@/components/ui/button";
import { ArrowRight, CheckCheck, ClipboardCheck, Coins, LayoutGrid, List, MessagesSquare, Package, RefreshCw, Search, ShoppingCart, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect,useRef,useState,type CSSProperties } from "react";
import styles from "./procurement-kanban.module.css";


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
  origin?: string;
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
  origin?: string;
  supplier?: string;
  quantity?: string;
  amount?: string;
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
const stageColors = ["#3B82F6", "#8B5CF6", "#F59E0B", "#06B6D4", "#EC4899", "#14B8A6", "#6366F1", "#F97316", "#22C55E"];

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Не удалось проверить закупки";
}

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { cache: "no-store", ...options });
  } catch {
    throw new Error("Не удалось связаться с сервисом закупок. Проверьте соединение и обновите канбан.");
  }
  if (!response.ok) {
    const message = response.status === 401 ? "Сессия истекла. Войдите в ERP заново."
      : response.status === 403 ? "Нет доступа к документам закупок. Проверьте права сотрудника."
      : response.status === 409 ? "Данные или права изменились. Обновите канбан перед следующим действием."
      : "Не удалось выполнить запрос закупок. Обновите канбан для проверки текущих данных.";
    throw new Error(`${message} (HTTP ${response.status})`);
  }
  let body: string;
  try {
    body = await response.text();
  } catch {
    throw new Error("Не удалось прочитать ответ сервиса закупок. Обновите канбан для проверки текущих данных.");
  }
  if (!body) throw new Error("Сервис закупок вернул пустой ответ");
  try {
    return JSON.parse(body) as T;
  } catch {
    throw new Error("Сервис закупок вернул некорректный ответ");
  }
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
      origin: request.origin,
      supplier: request.supplier || "Поставщик не указан",
      quantity: request.quantity,
      amount: request.planned_amount,
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

export function ProcurementKanban(props: { suggestedOrg?: string }) {
  return <div className={styles.workspace}><InstanceOrganizationGate>{org => <section aria-label="Рабочее место закупок">
    {props.suggestedOrg && props.suggestedOrg !== String(org.id) ? <p role="alert">Юрлицо ссылки не совпадает с настройкой установки.</p> : <CompanyKanban key={org.id} org={org.id} />}
  </section>}</InstanceOrganizationGate></div>;
}

function CompanyKanban({ org }: { org: number }) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [requestNext, setRequestNext] = useState<number | null>(null);
  const [orderNext, setOrderNext] = useState<number | null>(null);
  const [chains, setChains] = useState<Record<number, ChainState>>({});
  const [busy, setBusy] = useState(true);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"board" | "list">("board");
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
  const overview = [
    { label: "Заявки в работе", stages: ["need", "sourcing", "nego", "analysis", "approval"] as StageId[], href: `/erp/procurement/planning?org=${org}` },
    { label: "Заказы поставщикам", stages: ["po"] as StageId[], href: `/erp/procurement/orders?org=${org}` },
    { label: "Поставка", stages: ["supply"] as StageId[], href: `/erp/procurement/orders?org=${org}` },
    { label: "Приёмка", stages: ["qc"] as StageId[], href: `/erp/procurement/receipts?org=${org}` },
    { label: "Завершено", stages: ["done"] as StageId[], href: `/erp/procurement/orders?org=${org}` },
  ];
  const partial = requestNext !== null || orderNext !== null;
  const available = !!identity && !error;
  const ready = available && !busy;
  const filteredCards = cards.filter(card => `${card.title} ${card.subtitle} ${card.meta}`.toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru")));
  const count = (stages: StageId[]) => ready ? `${cards.filter(card => stages.includes(card.stage)).length}${partial ? "+" : ""}` : "—";
  const metrics = [
    { label: "Заявки в работе", value: count(requestStages), caption: "По загруженным документам", Icon: ShoppingCart, tone: "blue" },
    { label: "План по сумме закупок", value: "—", caption: "План не подключён", Icon: Coins, tone: "green" },
    { label: "Экономия (AI)", value: "—", caption: "Нет подтверждённых данных", Icon: Sparkles, tone: "violet" },
    { label: "Переговоры AI (актив.)", value: "—", caption: "Нет подтверждённых данных", Icon: MessagesSquare, tone: "amber" },
    { label: "Приёмка / QC", value: count(["qc"]), caption: "Ожидают подтверждения приёмки", Icon: ClipboardCheck, tone: "cyan" },
  ];
  function renderCard(card: Card) {
    return <article key={card.id} className={styles.card}>
      <Link className={styles.cardNumber} href={card.href}>{card.title}<ArrowRight size={14} aria-hidden /></Link>
      <p className={styles.cardTitle}>{card.subtitle}</p>
      {card.supplier && <p className={styles.supplier}><Package size={13} aria-hidden />{card.supplier}</p>}
      {card.origin === "deficit" && <p className={styles.sourceBadge}>Авто: дефицит склада</p>}
      {card.quantity !== undefined ? <>
        <div className={styles.cardRow}><span>Количество</span><strong>{card.quantity} шт.</strong></div>
        <div className={styles.cardRow}><span>Оценка суммы</span><strong className={styles.amount}>{card.amount}</strong></div>
        <p className={styles.cardMeta}>Валюта не задана</p>
      </> : <p className={styles.cardMeta}>{card.meta}</p>}
      {card.note && <p className={styles.cardNote}>{card.note}</p>}
      {card.action && <div className={styles.cardFooter}><Button size="sm" variant="ghost" disabled={busy || !identity?.can_manage} onClick={() => advance(card.action!)}>Далее: {stageTitles[nextRequestStage[card.action.stage]]}<ArrowRight size={13} aria-hidden /></Button></div>}
    </article>;
  }
  return <div className={styles.dashboard}>
    <header className={styles.pageHeader}>
      <div>
        <p className={styles.eyebrow}>Рабочее место закупщика</p>
        <h1>Обзор и воронка</h1>
        <p className={styles.pageDescription}>От потребности до подтверждённой приёмки.</p>
      </div>
      <div className={styles.pageActions}>
        <Link href={`/erp/procurement/planning?org=${org}`}><ShoppingCart size={16} aria-hidden />План закупок</Link>
        <Link href={`/erp/procurement/orders?org=${org}`}>Заказы и поставки<ArrowRight size={15} aria-hidden /></Link>
      </div>
    </header>
    {!identity && !error && <p role="status">Загрузка документов закупок…</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {notice && <p role="status" className={styles.notice}>{notice}</p>}
    <section aria-label="Показатели закупок">
      <div className={styles.sectionHeading}><h2>План — Факт</h2><span>По документам нашей организации</span></div>
      <div className={styles.kpis} role="group" aria-label="Карточки показателей закупок" tabIndex={0}>{metrics.map(({ label, value, caption, Icon, tone }) => <div className={styles.kpi} key={label}>
        <div className={styles.kpiHeading}><span className={`${styles.kpiIcon} ${styles[tone]}`}><Icon size={18} aria-hidden /></span><h3>{label}</h3></div>
        <p className={styles.kpiValue}>{value}</p><div className={styles.kpiLine} aria-hidden /><p className={styles.kpiCaption}>{caption}</p>
      </div>)}</div>
      <p className={styles.mobileHint}>Листайте показатели по горизонтали →</p>
    </section>
    <div className={styles.controlBar}><span className={styles.controlIcon}><CheckCheck size={19} aria-hidden /></span>
      <p><strong>Контроль закупок</strong> Поставка и приёмка подтверждаются статусом заказа и первичными документами.{ready ? ` На согласовании: ${count(["approval"])}.` : " Документы ещё не подтверждены."}</p>
      <Link href={`/erp/procurement/receipts?org=${org}`}>Проверить приёмку<ArrowRight size={14} aria-hidden /></Link>
    </div>
    <div className={styles.boardTools}>
      <h2>Воронка закупок</h2>
      <div className={styles.segment} role="group" aria-label="Вид закупок">
        <button type="button" aria-label="Канбан" aria-pressed={view === "board"} onClick={() => setView("board")}><LayoutGrid size={17} aria-hidden /></button>
        <button type="button" aria-label="Список" aria-pressed={view === "list"} onClick={() => setView("list")}><List size={18} aria-hidden /></button>
      </div>
      <span className={styles.statusPill}><span />На согласовании: {count(["approval"])}</span>
      <div className={styles.toolActions}>
        <label className={styles.search}><Search size={16} aria-hidden /><input aria-label="Поиск по закупкам, поставщикам, SKU" placeholder="Поиск по закупкам, поставщикам, SKU…" value={query} onChange={event => setQuery(event.target.value)} /></label>
        <Button disabled={busy} variant="secondary" icon={<RefreshCw size={15} />} onClick={() => run(refresh)}>Обновить канбан</Button>
      </div>
    </div>
    {query.trim() && <p className={styles.scopeNote}>Поиск среди загруженных документов: {available ? filteredCards.length : "—"}. Показатели выше относятся ко всем загруженным документам.</p>}
    {busy && identity && <p role="status">Обновление документов закупок…</p>}
    <div className={view === "board" ? styles.board : styles.list} aria-label={view === "board" ? "Канбан закупок" : "Список закупок"}>
      {(Object.keys(stageTitles) as StageId[]).map((stage, index) => <section key={stage} aria-label={`Колонка ${stageTitles[stage]}`} className={styles.column} style={{ "--stage-color": stageColors[index] } as CSSProperties}>
        <header className={styles.columnHead}><h2><span className={styles.stagePin} aria-hidden />{index + 1} · {stageTitles[stage]}</h2><p><strong>{available ? filteredCards.filter(card => card.stage === stage).length : "—"}</strong> документов{partial ? " · загружено не всё" : ""}</p></header>
        <div className={styles.columnBody}>{available && filteredCards.filter(card => card.stage === stage).map(renderCard)}
          {(!available || !filteredCards.some(card => card.stage === stage)) && <p className={styles.empty}>{!available ? error ? "Данные недоступны." : "Загрузка документов…" : query.trim() ? "Нет совпадений на этом этапе." : partial ? "Нет среди загруженных документов." : "Нет документов на этом этапе."}</p>}
        </div>
      </section>)}
    </div>
    {partial && <div className={styles.pagination}><p>Показана первая страница документов; незагруженные строки не считаются пустыми этапами.</p>{requestNext !== null && <Button disabled={busy} variant="secondary" onClick={() => loadMore("request", requestNext)}>Загрузить ещё заявки</Button>}{orderNext !== null && <Button disabled={busy} variant="secondary" onClick={() => loadMore("order", orderNext)}>Загрузить ещё заказы</Button>}</div>}
    <section aria-label="Оперативный обзор закупок" className={styles.summary}>
      <div className={styles.sectionHeading}><h2>Итоги по воронке закупок</h2><span>По загруженным документам{partial ? " · данные неполные" : ""}</span></div>
      <div className={styles.summaryGrid}>{overview.map(item => <Link key={item.label} href={item.href}><p>{item.label}</p><p className={styles.summaryValue}>{count(item.stages)}</p></Link>)}</div>
      {available && cancelled > 0 && <p className={styles.scopeNote}>Отменённых заказов вне канбана: {cancelled}. Их можно проверить в разделе заказов поставщикам.</p>}
    </section>
    {identity && !identity.can_manage && <p className={styles.scopeNote}>Доступен просмотр. Перевод заявки между этапами доступен главному бухгалтеру этого юрлица с доступом к закупкам.</p>}
  </div>;
}
