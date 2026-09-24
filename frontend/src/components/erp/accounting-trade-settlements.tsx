"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { compareTradeDocumentCsv, EXTERNAL_TRADE_HEADER, type TradeComparison } from "./accounting-trade-settlement-compare";

type Movement = { entry_id: number; line_id: number; date: string; source: string; operation: string;
  source_version: number; side: "debit" | "credit"; amount_byn: string; period_bucket: "opening" | "movement";
  kind: "posting" | "bank_receipt" | "bank_payment" | "advance_offset" };
type Row = { key: string; account: string; account_title: string; category: string; counterparty: string | null;
  contract: string | null; document: string | null; currencies: string[];
  classification: string; balance_kind: string;
  analytics_complete: boolean; opening_byn: string; debit_byn: string; credit_byn: string;
  closing_byn: string; bank_receipts_byn: string; bank_payments_byn: string;
  offset_debit_byn: string; offset_credit_byn: string; movements: Movement[] };
type Reconciliation = { status: "matched" | "mismatch"; basis: "same_posted_journal";
  osv_line_count: number; document_line_count: number; missing_osv_lines: number;
  extra_document_lines: number; missing_postings: { entry_id: number; line_id: number }[];
  accounts: { account: string; matched: boolean; osv_byn: Record<string, string>;
    documents_byn: Record<string, string> }[] };
type Report = { organization_id: number; from: string; to: string; status: "preliminary";
  scope: "posted_accounts_60_62"; due_dates_verified: false; statutory_certified: false;
  review_items: { code: string; count: number }[]; osv_reconciliation: Reconciliation;
  totals_byn: Record<string, string>; rows: Row[] };

const kinds: Record<string, string> = { receivable: "Дебиторская задолженность", payable: "Кредиторская задолженность",
  customer_advance: "Аванс покупателя", supplier_advance: "Аванс поставщику",
  unclassified: "Требует классификации", settled: "Закрыто" };
const movements: Record<Movement["kind"], string> = {
  posting: "Проводка", bank_receipt: "Банковское поступление",
  bank_payment: "Банковская выплата", advance_offset: "Зачёт аванса",
};
type Filter = "all" | "receivable" | "payable" | "advances" | "unclassified";

const csvText = (value: string | null) => {
  const raw = value ?? "";
  const safe = /^[\s\uFEFF]*[=+\-@]/u.test(raw) ? `'${raw}` : raw;
  return `"${safe.replaceAll('"', '""')}"`;
};
const csvAmount = (value: string) => {
  if (!/^-?\d+\.\d{2}$/.test(value)) throw new Error("Некорректная сумма в отчёте.");
  return value;
};
const csvId = (value: number) => {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error("Некорректная ссылка на проводку.");
  return String(value);
};

export function buildTradeSettlementsCsv(report: Report): string {
  const check = report.osv_reconciliation;
  const count = report.rows.reduce((sum, row) => sum + row.movements.length, 0);
  if (check.status !== "matched" || check.osv_line_count !== count || check.document_line_count !== count
      || check.missing_osv_lines || check.extra_document_lines || check.accounts.some((account) => !account.matched)) {
    throw new Error("Выгрузка недоступна: документная сводка не совпадает с ОСВ.");
  }
  const header = ["organization_id", "period_start", "period_end", "status", "account", "category",
    "counterparty", "contract", "settlement_document", "currencies", "opening_byn", "debit_byn",
    "credit_byn", "closing_byn", "movement_count", "entry_line_ids", "source_references_json"];
  const lines = report.rows.map((row) => [
    csvId(report.organization_id), csvText(report.from), csvText(report.to), csvText("preliminary_internal"),
    csvText(row.account), csvText(row.category), csvText(row.counterparty), csvText(row.contract),
    csvText(row.document), csvText(row.currencies.join("|")), csvAmount(row.opening_byn),
    csvAmount(row.debit_byn), csvAmount(row.credit_byn), csvAmount(row.closing_byn),
    String(row.movements.length),
    csvText(row.movements.map((movement) => `${csvId(movement.entry_id)}:${csvId(movement.line_id)}`).join("|")),
    csvText(JSON.stringify(row.movements.map((movement) => ({
      source: movement.source, source_version: csvId(movement.source_version),
    })))),
  ].join(","));
  return `\uFEFF${[header.join(","), ...lines].join("\r\n")}\r\n`;
}

function downloadLocalCsv(contents: string, filename: string) {
  const url = URL.createObjectURL(new Blob([contents], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function AccountingTradeSettlements({ org, start, end, onEntry }: {
  org: string; start: string; end: string; onEntry: (id: number) => void;
}) {
  const [savedReport, setSavedReport] = useState<{ scope: string; data: Report } | null>(null);
  const [savedError, setSavedError] = useState<{ scope: string; message: string } | null>(null);
  const [savedFilter, setSavedFilter] = useState<{ scope: string; value: Filter } | null>(null);
  const [comparison, setComparison] = useState<{ scope: string; filename: string; sha256: string;
    result: TradeComparison } | null>(null);
  const [comparisonError, setComparisonError] = useState<{ scope: string; message: string } | null>(null);
  const [refresh, setRefresh] = useState(0);
  const scope = `${org}/${start}/${end}/${refresh}`;
  const currentScope = useRef(scope);
  useEffect(() => { currentScope.current = scope; }, [scope]);
  const report = savedReport?.scope === scope ? savedReport.data : null;
  const error = savedError?.scope === scope ? savedError.message : "";
  const filter = savedFilter?.scope === scope ? savedFilter.value : "all";
  const loading = !!org && !report && !error;

  function downloadCsv() {
    if (!report || report.organization_id !== Number(org) || report.from !== start || report.to !== end) return;
    try {
      downloadLocalCsv(buildTradeSettlementsCsv(report),
        `trade-settlements-org-${report.organization_id}-${report.from}-${report.to}.csv`);
    } catch (reason) {
      setSavedError({ scope, message: reason instanceof Error ? reason.message : "Не удалось подготовить CSV." });
    }
  }

  async function compareFile(file: File) {
    const selectedScope = scope;
    setComparison(null);
    setComparisonError(null);
    try {
      if (!report || report.organization_id !== Number(org) || report.from !== start || report.to !== end) return;
      buildTradeSettlementsCsv(report); // Requires the exact internally matched ERP population.
      if (!file.size || file.size > 10 * 1024 * 1024) throw new Error("CSV 1С должен быть непустым и не больше 10 МБ.");
      const bytes = await file.arrayBuffer();
      const sha256 = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)))
        .map((byte) => byte.toString(16).padStart(2, "0")).join("");
      let source: string;
      try { source = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
      catch { throw new Error("CSV 1С должен быть в кодировке UTF-8."); }
      if (currentScope.current !== selectedScope) return;
      const result = compareTradeDocumentCsv(source, report);
      if (currentScope.current === selectedScope) setComparison({ scope, filename: file.name, sha256, result });
    } catch (reason) {
      if (currentScope.current === selectedScope) setComparisonError({ scope,
        message: reason instanceof Error ? reason.message : "Не удалось сравнить CSV 1С." });
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    if (!org) return () => { active = false; controller.abort(); };
    const query = new URLSearchParams({ start, end });
    void fetch(`/api/accounting/organizations/${encodeURIComponent(org)}/reports/trade-settlements?${query}`, {
      cache: "no-store", signal: controller.signal,
    }).then(async (response) => {
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "Не удалось загрузить расчёты.");
      if (data.organization_id !== Number(org) || data.from !== start || data.to !== end || data.scope !== "posted_accounts_60_62") {
        throw new Error("Ответ расчётов не соответствует выбранной книге или периоду.");
      }
      if (active) setSavedReport({ scope, data: data as Report });
    }).catch((reason: Error) => { if (active && reason.name !== "AbortError") setSavedError({ scope, message: reason.message }); });
    return () => { active = false; controller.abort(); };
  }, [org, start, end, refresh, scope]);

  const visible = report?.rows.filter((row) => filter === "all" || row.balance_kind === filter
    || filter === "advances" && ["customer_advance", "supplier_advance"].includes(row.balance_kind)) ?? [];

  return <section aria-label="Торговые расчёты" className="space-y-4">
    <header><h2 className="text-xl font-semibold">Торговые расчёты по документам</h2>
      <p className="text-sm text-muted">Проведённые строки счетов 60/62 в BYN за выбранный период. Сроки оплаты и просрочка пока не подтверждены; это предварительный отчёт, не форма для сдачи.</p></header>
    {!org && <p>Выберите организацию, чтобы открыть расчёты.</p>}
    {loading && <p role="status">Загрузка расчётов…</p>}
    {error && <div role="alert" className="rounded-lg border border-red-300 p-3 text-red-700">{error} <Button variant="secondary" onClick={() => setRefresh((value) => value + 1)}>Повторить</Button></div>}
    {report && <>
      <p className="text-sm text-muted">{report.from} — {report.to} · только проведённая книга юрлица № {report.organization_id}. Аванс отмечен лишь при явном документе аванса; иные встречные сальдо требуют проверки.</p>
      {report.osv_reconciliation.status === "matched"
        ? <p role="status" className="rounded-lg border border-green-300 p-3 text-sm">Внутренняя сверка с ОСВ: суммы в BYN и строки 60/62 совпали (количество: {report.osv_reconciliation.document_line_count}). Оба отчёта построены по одной книге; это не сверка с 1С.</p>
        : <div role="alert" className="rounded-lg border border-red-300 p-3 text-sm text-red-700">
          <p className="font-semibold">Расхождение с ОСВ: документная сводка неполна. Не используйте её итог без проверки.</p>
          <p>Строк в ОСВ: {report.osv_reconciliation.osv_line_count}; в документной сводке: {report.osv_reconciliation.document_line_count}; пропущено: {report.osv_reconciliation.missing_osv_lines}; лишних: {report.osv_reconciliation.extra_document_lines}.</p>
          {report.osv_reconciliation.accounts.filter((account) => !account.matched).map((account) => <p key={account.account}>Счёт {account.account}, ОСВ / документы (BYN): начало {account.osv_byn.opening} / {account.documents_byn.opening}; Дт {account.osv_byn.debit} / {account.documents_byn.debit}; Кт {account.osv_byn.credit} / {account.documents_byn.credit}; конец {account.osv_byn.closing} / {account.documents_byn.closing}.</p>)}
          {report.osv_reconciliation.missing_postings.map((posting) => <button key={posting.line_id} className="mr-3 text-accent underline" onClick={() => onEntry(posting.entry_id)}>Проводка № {posting.entry_id}, строка {posting.line_id}</button>)}
        </div>}
      {report.osv_reconciliation.status === "matched" && <div><Button variant="secondary" onClick={downloadCsv}>Скачать CSV для внутренней сверки</Button><p className="text-xs text-muted">Файл содержит данные выбранной книги и периода. Это не акт сверки и не подтверждение данных 1С.</p></div>}
      {report.osv_reconciliation.status === "matched" && <section aria-label="Сравнение документов с 1С" className="space-y-3 rounded-lg border border-line bg-surface p-4">
        <h3 className="font-semibold">Сравнение документов с выгрузкой 1С</h3>
        <p className="text-sm text-muted">Нормализуйте выгрузку 1С по пустому шаблону: источник 1C, ID этой книги, выбранный период, один документ на строку и суммы в BYN. Сравнение использует точные текстовые аналитики; одноимённые объекты требуют отдельной проверки ID. Файл читается только в браузере, в ERP не отправляется. Название и совпадение сумм не доказывают происхождение файла или бухгалтерскую приёмку.</p>
        <Button variant="secondary" onClick={() => downloadLocalCsv(`\uFEFF${EXTERNAL_TRADE_HEADER.join(",")}\r\n`, "trade-settlements-1c-template.csv")}>Скачать пустой шаблон 1С</Button>
        <label className="block text-sm">Нормализованный CSV 1С
          <input aria-label="Нормализованный CSV 1С" type="file" accept=".csv,text/csv" className="mt-1 block w-full text-sm"
            onChange={(event) => { const file = event.currentTarget.files?.[0]; event.currentTarget.value = ""; if (file) void compareFile(file); }} />
        </label>
        {comparisonError?.scope === scope && <p role="alert" className="text-sm text-red-700">{comparisonError.message}</p>}
        {comparison?.scope === scope && <div className="space-y-2 text-sm">
          <p role={comparison.result.status === "matched" ? "status" : "alert"} className={comparison.result.status === "matched" ? "text-green-700" : "text-red-700"}>
            {comparison.result.status === "matched" ? "В выбранных файлах суммы документов совпали." : `Расхождения: ${comparison.result.issues.length}.`}
            {" "}ERP: {comparison.result.erp_rows}; 1С: {comparison.result.external_rows}; совпали: {comparison.result.matched_rows}. Это предварительная сверка, не акт приёмки.
          </p>
          <p className="break-all text-xs text-muted">Выбранный файл: {comparison.filename}; SHA-256 его байтов: {comparison.sha256}. Сверьте этот отпечаток с независимым пакетом исходных документов.</p>
          {comparison.result.issues.map((issue, index) => <div key={`${issue.kind}:${index}`} className="rounded border border-red-200 p-2">
            <p className="font-medium">{issue.kind === "missing_in_1c" ? "Есть в ERP, отсутствует в файле 1С" : issue.kind === "only_in_1c" ? "Есть в файле 1С, отсутствует в ERP" : "Суммы различаются"}: {issue.identity.account} · {issue.identity.counterparty} · {issue.identity.contract} · {issue.identity.document}</p>
            {issue.differing_fields.map((field) => <p key={field}>{field}: ERP {issue.erp?.[field]} / 1С {issue.external?.[field]} BYN</p>)}
            {issue.erp?.movements.map((movement) => <button key={movement.line_id} className="mr-3 text-accent underline" onClick={() => onEntry(movement.entry_id)}>Проводка № {movement.entry_id}, строка {movement.line_id}</button>)}
          </div>)}
        </div>}
      </section>}
      {report.osv_reconciliation.status === "matched" && <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">{[
        ["Дебиторка", "receivable"], ["Кредиторка", "payable"], ["Авансы покупателей", "customer_advance"],
        ["Авансы поставщикам", "supplier_advance"], ["Не классифицировано", "unclassified"],
      ].map(([label, key]) => <div key={key} className="rounded-lg border border-line bg-surface p-3"><p className="text-sm text-muted">{label}</p><p className="font-semibold tabular-nums">{report.totals_byn[key]} BYN</p></div>)}</div>}
      {report.review_items.some((item) => item.count > 0) && <p role="status" className="rounded-lg border border-amber-300 p-3 text-sm">Требуют проверки: неполная аналитика — {report.review_items.find((item) => item.code === "incomplete_analytics")?.count ?? 0}; не классифицированное сальдо — {report.review_items.find((item) => item.code === "unclassified_balance")?.count ?? 0}; документы с разной валютной атрибуцией — {report.review_items.find((item) => item.code === "mixed_currency_document")?.count ?? 0}.</p>}
      <label className="block max-w-xs text-sm">Показать<Select aria-label="Вид расчётов" value={filter} onChange={(event) => setSavedFilter({ scope, value: event.target.value as Filter })}>
        <option value="all">Все документы</option><option value="receivable">Дебиторка</option><option value="payable">Кредиторка</option>
        <option value="advances">Авансы</option><option value="unclassified">Требуют проверки</option>
      </Select></label>
      <div className="space-y-2">{visible.map((row) => <details key={row.key} className="rounded-lg border border-line bg-surface p-3">
        <summary className="cursor-pointer"><span className="font-medium">{row.counterparty ?? "Контрагент не указан"} · {row.document ?? "Документ не указан"}</span>
          <span className="ml-2 text-sm text-muted">{row.account} · {kinds[row.balance_kind] ?? "Требует проверки"} · {row.closing_byn} BYN</span></summary>
        <p className="mt-2 text-sm text-muted">Договор: {row.contract ?? "не указан"} · {row.account_title} · валютная атрибуция: {row.currencies.join(", ")}. {row.analytics_complete ? "Аналитика заполнена." : "Неполная аналитика: строка не объединена с другими документами."}{row.currencies.length > 1 ? " Смешанная валюта документа требует сверки с первичкой." : ""}</p>
        <div className="mt-2 overflow-x-auto"><table className="min-w-[690px] w-full text-sm"><thead><tr>{["Начало", "Дт периода", "Кт периода", "Конец", "Банк: поступило", "Банк: выплачено", "Зачёт Дт/Кт"].map((title) => <th key={title} className="border-b border-line p-2 text-right">{title}</th>)}</tr></thead>
          <tbody><tr>{[row.opening_byn, row.debit_byn, row.credit_byn, row.closing_byn, row.bank_receipts_byn, row.bank_payments_byn, `${row.offset_debit_byn} / ${row.offset_credit_byn}`].map((value, index) => <td key={index} className="p-2 text-right tabular-nums">{value}</td>)}</tr></tbody></table></div>
        <div className="mt-3 space-y-1"><h3 className="font-medium">Проводки и основания</h3>{row.movements.map((movement) => <p key={movement.line_id} className="text-sm">
          <button className="text-accent underline" onClick={() => onEntry(movement.entry_id)}>№ {movement.entry_id}</button> · {movement.date} · {movements[movement.kind]} · {movement.side === "debit" ? "Дт" : "Кт"} {movement.amount_byn} BYN · {movement.source}{movement.period_bucket === "opening" ? " · до периода" : ""}
        </p>)}</div>
      </details>)}{!visible.length && <p className="text-sm text-muted">По выбранному фильтру проводок нет.</p>}</div>
    </>}
  </section>;
}
