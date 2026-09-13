"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";

type Protocol = { status: string; cutover_ready?: boolean; accepted_by_accountant?: boolean; eligibility_blockers?: string[]; receipt_id?: number; left: { from: string; to: string; sha256: string; status: string; pending_documents?: number }; right: { sha256: string; status: string; pending_documents?: number }; differences: { account: string; dimensions: Record<string, string>; currency: string; off_balance: boolean; presence: string; fields: Record<string, { left: string | null; right: string | null; right_minus_left: string | null }> }[] };
async function encoded(file: File) {
  if (file.size > 2_000_000) throw new Error("Каждый файл должен быть не больше 2 МБ.");
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 8192) binary += String.fromCharCode(...bytes.subarray(index, index + 8192));
  return btoa(binary);
}
const labels: Record<string, string> = { opening: "Начальное сальдо BYN", debit: "Дебет BYN", credit: "Кредит BYN", closing: "Конечное сальдо BYN", original_opening: "Начальное сальдо в валюте", original_debit: "Дебет в валюте", original_credit: "Кредит в валюте", original_closing: "Конечное сальдо в валюте", quantity_opening: "Начальное количество", quantity_debit: "Приход количества", quantity_credit: "Расход количества", quantity_closing: "Конечное количество" };
const reportStatus = (status: string) => status === "preliminary" ? "предварительные данные" : status === "closed_periods" ? "периоды закрыты" : "неизвестный статус";
export function AccountingReconciliation({ org }: { org: string }) {
  const [left, setLeft] = useState<File | null>(null), [right, setRight] = useState<File | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [protocol, setProtocol] = useState<Protocol | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false), [confirmKey, setConfirmKey] = useState("");
  const [evidence, setEvidence] = useState("");
  async function compare() {
    if (!org || !left || !right || busy) return;
    setBusy(true); setError(""); setProtocol(null);
    try {
      const [left_base64, right_base64] = await Promise.all([encoded(left), encoded(right)]);
      const response = await fetch(`/api/accounting/organizations/${org}/reconciliation`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ left_base64, right_base64 }) });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Проверьте формат файлов и доступ к книге.");
      setProtocol(result); setConfirmKey(result.cutover_ready ? crypto.randomUUID() : ""); setEvidence("");
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось выполнить сверку."); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!org || !left || !right || !protocol?.cutover_ready || protocol.accepted_by_accountant || !confirmKey || evidence.trim().length < 10 || confirmBusy) return;
    setConfirmBusy(true); setError("");
    try {
      const [left_base64, right_base64] = await Promise.all([encoded(left), encoded(right)]);
      const response = await fetch(`/api/accounting/organizations/${org}/reconciliation/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ left_base64, right_base64, request_key: confirmKey, evidence: evidence.trim() }) });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Не удалось сохранить протокол сверки.");
      if (String(result.organization_id) !== org || result.request_key !== confirmKey || result.accepted_by_accountant !== true || result.cutover_ready !== true) throw new Error("Сервер вернул неподтверждённый протокол сверки.");
      setProtocol({ ...protocol, accepted_by_accountant: true, receipt_id: result.receipt_id });
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить протокол сверки."); }
    finally { setConfirmBusy(false); }
  }
  function download() {
    if (!protocol) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(protocol, null, 2)], { type: "application/json;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `osv-comparison-${org}-${protocol.left.from}-${protocol.left.to}.json`;
    document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const clear = () => { setProtocol(null); setError(""); setConfirmKey(""); setEvidence(""); };
  return <section aria-label="Сверка ОСВ" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Сверка двух ОСВ</h2>
    <p>Выберите два CSV в формате выгрузки ERP для одного юрлица и периода. Выгрузку 1С сначала приведите к этому формату по утверждённому соответствию счетов и аналитики. До 2 МБ на файл. Файлы отправляются серверу для сравнения; проводки не создаются.</p>
    <p className="text-sm text-muted">Период берётся из файлов. Разница: правая ОСВ минус левая. Отсутствующие строки не считаются нулевыми. Совпадение не заменяет проверку бухгалтера и закрытие месяца.</p>
    <fieldset disabled={busy || !org} className="space-y-3">
      <label className="block">Левая ОСВ<input className="block" type="file" accept=".csv,text/csv" onChange={(e) => { setLeft(e.target.files?.[0] ?? null); clear(); }} /></label>
      <label className="block">Правая ОСВ<input className="block" type="file" accept=".csv,text/csv" onChange={(e) => { setRight(e.target.files?.[0] ?? null); clear(); }} /></label>
      <Button disabled={!left || !right} onClick={() => void compare()}>Сравнить ОСВ</Button>
    </fieldset>
    {!org && <p>Выберите юрлицо.</p>}{busy && <p role="status">Сравнение файлов…</p>}{error && <p role="alert">{error}</p>}
    {protocol && <>
      <p>{protocol.status === "no_numeric_differences" ? "Числовых расхождений не найдено." : `Строк с расхождениями: ${protocol.differences.length}.`}</p>
      <p>{protocol.left.from} — {protocol.left.to} · Левая: {reportStatus(protocol.left.status)} · Правая: {reportStatus(protocol.right.status)}</p>
      {protocol.accepted_by_accountant ? <p role="status">Протокол принят бухгалтером{protocol.receipt_id ? ` · квитанция №${protocol.receipt_id}` : ""}. Повторная запись не создаётся.</p> : protocol.cutover_ready ? <div className="space-y-2 rounded border border-accent p-3"><p>ОСВ совпадают, оба отчёта закрыты и необработанных документов нет. Перед подтверждением проверьте протокол.</p><label className="block">Основание проверки<input aria-label="Основание принятия сверки" className="mt-1 block w-full rounded border border-line px-2 py-1" value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="Протокол сверки и подпись бухгалтера" /></label><Button disabled={confirmBusy || evidence.trim().length < 10} onClick={() => void confirm()}>{confirmBusy ? "Сохраняем…" : "Принять протокол бухгалтером"}</Button></div> : <p className="text-sm text-muted">Подтверждение недоступно: {(protocol.eligibility_blockers ?? ["нужны закрытые отчёты без необработанных документов"]).join(", ")}.</p>}
      <Button variant="secondary" onClick={download}>Скачать протокол JSON</Button>
      <p className="break-all text-xs">SHA-256 левой: {protocol.left.sha256}<br />SHA-256 правой: {protocol.right.sha256}</p>
      {protocol.differences.slice(0, 100).map((row, index) => <article key={index} className="rounded border border-line p-3">
        <p>{row.account} · {row.currency}{row.off_balance ? " · Забалансовый" : ""} · {row.presence === "left_only" ? "Только в левой ОСВ" : row.presence === "right_only" ? "Только в правой ОСВ" : "Есть в обеих ОСВ"}</p>
        <p>{JSON.stringify(row.dimensions)}</p>
        {Object.entries(row.fields).map(([field, values]) => <p key={field}>{labels[field] ?? field}: слева {values.left ?? "нет строки"}; справа {values.right ?? "нет строки"}; разница {values.right_minus_left ?? "не рассчитывается"}</p>)}
      </article>)}
      {protocol.differences.length > 100 && <p>Показаны первые 100 строк. Полный список находится в скачиваемом протоколе.</p>}
    </>}
  </section>;
}
