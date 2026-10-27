"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import * as expenseApi from "@/lib/expense-control-api";
import { fetchBom, type Bom } from "@/lib/production-bom";

type ComponentRow = { name: string; unit: string; per_unit: string; loss_percent: string; unit_cost_byn: string; price_basis: string };
const emptyRow = (): ComponentRow => ({ name: "", unit: "шт", per_unit: "1", loss_percent: "0", unit_cost_byn: "", price_basis: "" });
const costLabels = {
  labor_byn: "Оплата сборки", contributions_byn: "Взносы с оплаты сборки", subcontract_byn: "Услуги подрядчиков",
  overhead_byn: "Производственные накладные", packaging_byn: "Упаковка изделия",
};
type CostKey = keyof typeof costLabels;
type Estimate = { organization_id: number; status: "estimated" | "incomplete"; input: unknown; total_cost_byn: string | null;
  unit_cost_byn: string | null; revenue_net_byn: string | null; gross_profit_byn: string | null; margin_percent: string | null;
  missing_price_lines: number[]; known_components_byn: string; batch_costs_byn: string;
  cost_article_snapshots?: Partial<Record<CostKey, { id: number; code: string; title: string; group_title: string }>>;
  lines: { line_no: number; name: string; unit: string; quantity: string; cost_byn: string | null }[] };
const decimal = (value: string) => value.trim().replace(",", ".");

export function AccountingAssemblyEstimate({ org, date }: { org: string; date: string }) {
  // Remount on organization/date changes so an estimate can never belong to another book.
  return <EstimateForm key={`${org}/${date}`} org={org} date={date} />;
}

function EstimateForm({ org, date }: { org: string; date: string }) {
  const [product, setProduct] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [purpose, setPurpose] = useState("customer_order");
  const [reference, setReference] = useState("");
  const [specification, setSpecification] = useState("");
  const [price, setPrice] = useState("");
  const [components, setComponents] = useState<ComponentRow[]>([emptyRow()]);
  const [costs, setCosts] = useState<Record<CostKey, string>>({ labor_byn: "0", contributions_byn: "0", subcontract_byn: "0", overhead_byn: "0", packaging_byn: "0" });
  const [costArticles, setCostArticles] = useState<Record<CostKey, string>>({ labor_byn: "", contributions_byn: "", subcontract_byn: "", overhead_byn: "", packaging_byn: "" });
  const [expenseCatalog, setExpenseCatalog] = useState<expenseApi.Catalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [boms, setBoms] = useState<Bom[]>([]);
  const [bomId, setBomId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Estimate | null>(null);
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);
  useEffect(() => {
    if (!org) return;
    let alive = true;
    void expenseApi.context(Number(org)).then(value => {
      if (alive) setExpenseCatalog(value.catalog);
    }).catch(e => {
      if (alive) { setExpenseCatalog(null); setCatalogError((e as Error).message); }
    });
    return () => { alive = false; };
  }, [org]);
  const activeArticles = (expenseCatalog?.articles ?? []).filter(article => article.active
    && expenseCatalog?.groups.some(group => group.id === article.group_id && group.active));

  function changed() { generation.current += 1; setResult(null); setError(""); setBusy(false); }
  function edit(index: number, field: keyof ComponentRow, value: string) {
    changed(); setComponents(rows => rows.map((row, i) => i === index ? { ...row, [field]: value } : row));
  }
  async function loadBoms() {
    const current = ++generation.current;
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/production/boms", { cache: "no-store" });
      if (!response.ok) throw new Error("Не удалось загрузить спецификации. Можно ввести состав вручную.");
      const rows: Bom[] = await response.json();
      if (!Array.isArray(rows)) throw new Error("Некорректный список спецификаций");
      if (current === generation.current) { setBoms(rows); if (!rows.length) setError("Спецификаций пока нет. Введите состав вручную."); }
    } catch (e) { if (current === generation.current) setError((e as Error).message); }
    finally { if (current === generation.current) setBusy(false); }
  }
  async function loadSelectedBom() {
    const current = ++generation.current;
    setBusy(true); setError(""); setResult(null);
    const bom = await fetchBom(Number(bomId));
    if (current !== generation.current) return;
    setBusy(false);
    if (!bom || !bom.items.length) { setError("Не удалось получить непустой состав спецификации."); return; }
    setProduct(bom.product); setSpecification(`BOM ${bom.id} · ${bom.version} · ${bom.status === "approved" ? "утверждена" : "черновик"}`);
    setComponents(bom.items.map(row => ({ ...emptyRow(), name: row.component, unit: row.unit, per_unit: String(row.norm_qty) })));
  }
  async function calculate() {
    const current = ++generation.current;
    setBusy(true); setError(""); setResult(null);
    try {
      const input = { product, quantity: decimal(quantity), purpose, reference, specification, as_of: date,
        components: components.map(row => ({ ...row, per_unit: decimal(row.per_unit), loss_percent: decimal(row.loss_percent), unit_cost_byn: row.unit_cost_byn.trim() ? decimal(row.unit_cost_byn) : null })),
        batch_costs: Object.fromEntries(Object.entries(costs).map(([key, value]) => [key, decimal(value)])),
        batch_cost_articles: (Object.entries(costArticles) as [CostKey, string][]).filter(([, id]) => id !== "")
          .map(([category, id]) => ({ category, article_id: Number(id) })),
        sale_unit_net_byn: price.trim() ? decimal(price) : null };
      const response = await fetch(`/api/accounting/organizations/${org}/assembly-estimate`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input), cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте положительное количество, состав, источник каждой цены и неотрицательные затраты. Используйте не более 6 знаков после запятой для цены и количества.");
      if (String(data.organization_id) !== org || !Array.isArray(data.lines)) throw new Error("Расчёт не соответствует выбранной организации.");
      if (current === generation.current) setResult(data);
    } catch (e) { if (current === generation.current) setError((e as Error).message); }
    finally { if (current === generation.current) setBusy(false); }
  }
  function download() {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `assembly-estimate-${org}-${date}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section aria-label="Предварительная калькуляция сборки" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Предварительная калькуляция сборки</h2>
      <p className="text-sm text-muted">Расчёт на {date}. Все суммы — BYN. Цена комплектующего включает доставку и прочие затраты закупки, без возмещаемого НДС. Плановые затраты на всю партию указываются отдельно. Управленческие и сбытовые расходы в валовую прибыль не входят.</p>
    <p className="text-sm text-muted">Калькуляция не проводит документы и не меняет склад. Дополнительные затраты можно связать со статьями выбранной организации. Сохраните результат в файл перед уходом со страницы.</p>
    <fieldset disabled={busy || !org} className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <Button variant="secondary" onClick={() => void loadBoms()}>Загрузить спецификации</Button>
        {!!boms.length && <><Select aria-label="Спецификация BOM" value={bomId} onChange={e => setBomId(e.target.value)} className="max-w-lg"><option value="">Выберите состав</option>{boms.map(b => <option key={b.id} value={b.id}>{b.product} · {b.version}</option>)}</Select><Button variant="secondary" disabled={!bomId} onClick={() => void loadSelectedBom()}>Взять состав (заменить строки)</Button></>}
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Изделие"><Input value={product} onChange={e => { changed(); setProduct(e.target.value); }} /></Field>
        <Field label="Количество изделий"><Input inputMode="decimal" value={quantity} onChange={e => { changed(); setQuantity(e.target.value); }} /></Field>
        <Field label="Назначение"><Select value={purpose} onChange={e => { changed(); setPurpose(e.target.value); }}><option value="customer_order">Под заказ клиента</option><option value="stock">На склад</option></Select></Field>
        <Field label={purpose === "stock" ? "Обозначение партии" : "Номер заказа клиента"}><Input value={reference} onChange={e => { changed(); setReference(e.target.value); }} /></Field>
        <Field label="Спецификация / версия состава"><Input value={specification} onChange={e => { changed(); setSpecification(e.target.value); }} /></Field>
        <Field label="Плановая цена продажи за изделие без НДС"><Input inputMode="decimal" placeholder="Необязательно" value={price} onChange={e => { changed(); setPrice(e.target.value); }} /></Field>
      </div>
      <div className="overflow-x-auto"><table className="w-full text-sm"><caption className="text-left text-muted">Норма на изделие; запас на потери увеличивает расход на указанный процент. Пустая цена означает, что себестоимость пока неполная.</caption><thead><tr>{["Комплектующее", "Ед.", "Норма", "Запас на потери, %", "Цена BYN/ед.", "Источник цены", ""].map((name, i) => <th key={i} className="p-2 text-left">{name}</th>)}</tr></thead><tbody>
        {components.map((row, i) => <tr key={i}>{(["name", "unit", "per_unit", "loss_percent", "unit_cost_byn", "price_basis"] as const).map((field, j) => <td key={field} className="p-1"><Input aria-label={`${["Комплектующее", "Единица", "Норма", "Потери", "Цена", "Источник цены"][j]} ${i + 1}`} value={row[field]} onChange={e => edit(i, field, e.target.value)} className={j === 0 || j === 5 ? "min-w-44" : "min-w-24"} /></td>)}<td><Button variant="secondary" disabled={components.length === 1} onClick={() => { changed(); setComponents(rows => rows.filter((_, n) => n !== i)); }}>Удалить {i + 1}</Button></td></tr>)}
      </tbody></table></div>
      <Button variant="secondary" disabled={components.length >= 300} onClick={() => { changed(); setComponents(rows => [...rows, emptyRow()]); }}>Добавить комплектующее</Button>
      <h3 className="font-medium">Затраты на всю партию, BYN</h3>
      {catalogError && <p className="text-sm text-amber-800">Справочник не загружен: {catalogError}. Расчёт останется предварительным без привязки статьи.</p>}
      {expenseCatalog && !catalogError && activeArticles.length === 0 && <p className="text-sm text-muted">В справочнике пока нет активных статей. Их можно добавить в разделе «Контроль расходов»; суммы калькуляции при этом не проводятся.</p>}
      <div className="grid gap-3 md:grid-cols-3">{(Object.keys(costLabels) as CostKey[]).map(key => <div key={key} className="space-y-2 rounded border border-line p-3">
        <Field label={`${costLabels[key]}, BYN`}><Input inputMode="decimal" value={costs[key]} onChange={e => { changed(); setCosts(value => ({ ...value, [key]: e.target.value })); }} /></Field>
        <Field label={`Статья расходов: ${costLabels[key]}`}><Select aria-label={`Статья расходов: ${costLabels[key]}`} value={costArticles[key]} onChange={e => { changed(); setCostArticles(value => ({ ...value, [key]: e.target.value })); }}>
          <option value="">Не привязана</option>{activeArticles.map(article => {
            const group = expenseCatalog?.groups.find(item => item.id === article.group_id);
            return <option key={article.id} value={article.id}>{group?.title ?? "Без группы"} / {article.title}</option>;
          })}
        </Select></Field>
      </div>)}</div>
      <Button onClick={() => void calculate()}>Рассчитать</Button>
    </fieldset>
    {busy && <p role="status">Выполняется расчёт или загрузка…</p>}
    {!org && <p>Выберите организацию.</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {result && <div className="space-y-3 rounded-lg border border-line p-4">
      <h3 className="font-semibold">{result.status === "incomplete" ? "Неполная калькуляция" : "Плановая себестоимость"}</h3>
      {!!result.missing_price_lines.length && <p role="alert">Не указаны цены в строках: {result.missing_price_lines.join(", ")}. Общая себестоимость и прибыль не рассчитаны.</p>}
      <dl className="grid gap-2 md:grid-cols-3">{[
        ["Комплектующие с известной ценой", result.known_components_byn], ["Затраты на партию", result.batch_costs_byn],
        ["Себестоимость партии", result.total_cost_byn], ["Себестоимость изделия", result.unit_cost_byn],
        ["Плановая выручка без НДС", result.revenue_net_byn], ["Плановая валовая прибыль", result.gross_profit_byn],
      ].map(([label, value]) => <div key={label}><dt className="text-sm text-muted">{label}</dt><dd className="font-medium">{value === null ? "Не рассчитано" : `${value} BYN`}</dd></div>)}</dl>
      <p>Плановая валовая маржа: {result.margin_percent === null ? "не рассчитана" : `${result.margin_percent}%`}</p>
      <details><summary>Статьи дополнительных затрат</summary><ul>{(Object.keys(costLabels) as CostKey[]).map(key => {
        const article = result.cost_article_snapshots?.[key];
        return <li key={key}>{costLabels[key]}: {article ? `${article.group_title} / ${article.title} (${article.code})` : "статья не привязана"}</li>;
      })}</ul></details>
      <details><summary>Расход и стоимость комплектующих</summary><ul>{result.lines.map(line => <li key={line.line_no}>{line.name}: {line.quantity} {line.unit} — {line.cost_byn === null ? "цена неизвестна" : `${line.cost_byn} BYN`}</li>)}</ul></details>
      <Button variant="secondary" onClick={download}>Сохранить калькуляцию в файл</Button>
    </div>}
  </section>;
}
