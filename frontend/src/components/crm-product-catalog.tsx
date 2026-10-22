"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { fetchDealItems, fetchSalesSkusStrict, SalesCatalogError, type DealItemFull, type SkuOption } from "@/lib/api";
import { compactSkuCode } from "@/lib/catalog-picker-table";
import { CatalogPickerModal } from "@/components/kanban/catalog-picker-modal";
import { useProductPicker } from "@/components/kanban/product-picker";
import { useCurrency } from "@/components/kanban/currency-context";

type AvailableDeal = { id: string; number: string; title: string; counterparty: string };

function Selection({ deal, onClose, onItemsCommitted }: {
  deal: AvailableDeal; onClose: () => void; onItemsCommitted: (id: string) => void;
}) {
  const picker = useProductPicker(true, deal.id);
  return <CatalogPickerModal state={picker} dealId={deal.id} counterparty={deal.counterparty}
    onClose={onClose} onCommitted={onClose} onItemsCommitted={onItemsCommitted} />;
}

export function CrmProductCatalog() {
  const { fmt } = useCurrency();
  const [skus, setSkus] = useState<SkuOption[]>([]);
  const [catalogState, setCatalogState] = useState<"loading" | "ready" | "auth" | "error">("loading");
  const [deals, setDeals] = useState<AvailableDeal[]>([]);
  const [dealState, setDealState] = useState<"loading" | "ready" | "error">("loading");
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [dealId, setDealId] = useState("");
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<DealItemFull[] | null>(null);
  const [itemsError, setItemsError] = useState(false);
  const selectedId = useRef(dealId);
  selectedId.current = dealId;
  const alive = useRef(true);
  const readSequence = useRef(0);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; readSequence.current += 1; };
  }, []);

  useEffect(() => {
    let current = true;
    void fetchSalesSkusStrict().then((rows) => {
      if (current) { setSkus(rows); setCatalogState("ready"); }
    }).catch((error: unknown) => {
      if (current) {
        setSkus([]);
        setCatalogState(error instanceof SalesCatalogError && (error.status === 401 || error.status === 403) ? "auth" : "error");
      }
    });
    return () => { current = false; };
  }, [reload]);

  useEffect(() => {
    let current = true;
    void (async () => {
      try {
        const response = await fetch("/api/sales/deals", { cache: "no-store" });
        if (!response.ok) throw new Error("deals unavailable");
        const rows: unknown = await response.json();
        if (!Array.isArray(rows)) throw new Error("invalid deals");
        const ids = new Set<string>();
        const choices = rows.map((row: unknown) => {
          const d = row as Record<string, unknown> | null;
          if (!d || !Number.isSafeInteger(d.id) || Number(d.id) <= 0 || typeof d.number !== "string"
            || typeof d.title !== "string" || typeof d.counterparty !== "string" || ids.has(String(d.id))) throw new Error("invalid deal");
          ids.add(String(d.id));
          return { id: String(d.id), number: d.number, title: d.title, counterparty: d.counterparty };
        });
        if (current) { setDeals(choices); setDealState("ready"); }
      } catch {
        if (current) { setDeals([]); setDealState("error"); }
      }
    })();
    return () => { current = false; };
  }, [reload]);

  async function readItems(id: string) {
    const sequence = ++readSequence.current;
    try {
      const rows = await fetchDealItems(id, { throwOnError: true });
      if (alive.current && selectedId.current === id && readSequence.current === sequence) { setItems(rows); setItemsError(false); }
    } catch {
      if (alive.current && selectedId.current === id && readSequence.current === sequence) { setItems(null); setItemsError(true); }
    }
  }

  const selected = deals.find((d) => d.id === dealId);
  const filtered = skus.filter((sku) => `${sku.title} ${sku.code}`.toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru")));
  const pages = Math.max(1, Math.ceil(filtered.length / 50));
  const currentPage = Math.min(page, pages - 1);

  return <main className="w-full min-w-0 flex-1 space-y-4 p-4 sm:p-6">
    <section className="rounded-2xl bg-surface p-4 shadow-card">
      <h2 className="font-bold">Каталог товаров и подбор</h2>
      <p className="mt-2 text-sm text-muted">Найдите товар по названию или коду. Для подбора количества и цены выберите сделку. Товары попадут в неё после нажатия «Перенести в документ».</p>
      <div className="mt-3 flex min-w-0 flex-wrap items-end gap-3">
        <label className="min-w-0 flex-1">Сделка для подбора
          <select aria-label="Сделка для подбора" value={dealId} disabled={open || dealState !== "ready"}
            className="mt-1 w-full min-w-0 rounded-xl border border-line bg-surface p-2"
            onChange={(event) => { readSequence.current += 1; setDealId(event.target.value); setItems(null); setItemsError(false); }}>
            <option value="">Выберите доступную сделку</option>
            {deals.map((deal) => <option key={deal.id} value={deal.id}>{deal.number} · {deal.counterparty || deal.title}</option>)}
          </select>
        </label>
        <button type="button" disabled={!selected || open} onClick={() => setOpen(true)}
          className="rounded-xl bg-accent px-4 py-2 font-bold text-white disabled:opacity-50">Подобрать товары</button>
      </div>
      {dealState === "loading" && <p role="status">Загрузка доступных сделок…</p>}
      {dealState === "error" && <p role="alert">Не удалось загрузить доступные сделки. Перенос недоступен.</p>}
      {dealState === "ready" && deals.length === 0 && <p>Доступных сделок нет. <Link href="/crm/deals" className="text-accent underline">Открыть сделки</Link></p>}
      <p className="mt-2 text-sm text-muted">В подборе можно настроить столбцы и увидеть подтверждённые остатки, резервы и цены по складам. «—» означает отсутствие данных.</p>
      {itemsError && <p role="alert">Строки сделки не удалось перечитать. Проверьте их в карточке сделки перед повторным переносом.</p>}
      {items !== null && <div className="mt-3">
        <h3 className="font-bold">Товары выбранной сделки</h3>
        {items.map((item) => <p key={item.id} className="break-words">{item.title} · {item.qty} {item.unit} · {item.unit_price == null ? "цена не указана" : fmt(item.unit_price)}</p>)}
        {items.length === 0 && <p>В сделке пока нет товаров.</p>}
        {selected && <Link href={`/crm/deals/${selected.id}`} className="text-accent underline">Открыть сделку</Link>}
      </div>}
    </section>
    <section className="min-w-0 rounded-2xl bg-surface p-4 shadow-card">
      <h2 className="font-bold">Номенклатура</h2>
      <label className="mt-3 block">Поиск товара
        <input aria-label="Поиск товара" value={query} maxLength={1024}
          className="mt-1 w-full rounded-xl border border-line bg-surface p-2" placeholder="Название или код товара"
          onChange={(event) => { setQuery(event.target.value); setPage(0); }} />
      </label>
      {catalogState === "loading" && <p role="status">Загрузка каталога…</p>}
      {catalogState === "auth" && <p role="alert">Каталог продаж недоступен для вашей учётной записи. Проверьте вход и доступ к продажам.</p>}
      {catalogState === "error" && <p role="alert">Не удалось загрузить каталог. Количество товаров неизвестно.</p>}
      {(catalogState === "error" || catalogState === "auth" || dealState === "error") && <button type="button" disabled={open} onClick={() => {
        readSequence.current += 1; setCatalogState("loading"); setDealState("loading"); setSkus([]); setDeals([]); setDealId(""); setItems(null); setItemsError(false); setReload((n) => n + 1);
      }} className="mt-2 text-accent underline">Повторить загрузку</button>}
      {catalogState === "ready" && <>
        <p role="status" className="my-2">Найдено товаров: {filtered.length}</p>
        {filtered.length === 0 ? <p>{skus.length ? "По вашему запросу товары не найдены." : "В каталоге пока нет товаров."}</p> : <table className="w-full table-fixed text-sm">
          <colgroup><col className="w-1/5" /><col /><col className="w-14" /></colgroup>
          <thead><tr className="text-left text-muted"><th className="p-2">Код</th><th className="p-2">Наименование</th><th className="p-2">Ед.</th></tr></thead>
          <tbody>{filtered.slice(currentPage * 50, (currentPage + 1) * 50).map((sku) => <tr key={sku.id} className="border-t border-line">
            <td className="truncate p-2 font-mono" title={sku.code}>{compactSkuCode(sku.code)}</td><td className="break-words p-2">{sku.title}</td><td className="p-2">{sku.unit}</td>
          </tr>)}</tbody>
        </table>}
        {pages > 1 && <nav aria-label="Страницы каталога" className="mt-3 flex flex-wrap gap-3">
          <button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Назад</button>
          <span>Страница {currentPage + 1} из {pages}</span>
          <button type="button" disabled={currentPage + 1 === pages} onClick={() => setPage(currentPage + 1)}>Далее</button>
        </nav>}
      </>}
    </section>
    {open && selected && <Selection key={selected.id} deal={selected} onClose={() => setOpen(false)} onItemsCommitted={(id) => { void readItems(id); }} />}
  </main>;
}
