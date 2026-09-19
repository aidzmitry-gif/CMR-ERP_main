"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const template = "external_id,direction,operation_date,amount,currency,counterparty_name,counterparty_identifier,purpose\n";
type Preview = {
  valid: boolean; preview_digest: string; valid_count: number;
  totals: { receipt: string; payment: string };
  errors: { record: number; message: string }[];
};

export function AccountingBankStatementCsv({ org, disabled, onImported }: {
  org: string; disabled: boolean; onImported: () => Promise<void>;
}) {
  const [data, setData] = useState({ provider: "", account_code: "", evidence: "", content: "" });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  async function readFile(file?: File) {
    setPreview(null); setMessage(""); setError("");
    setData((current) => ({ ...current, content: "" }));
    if (!file) return;
    if (file.size > 1_000_000) { setError("Файл должен быть не больше 1 МБ."); return; }
    setBusy(true);
    try {
      const content = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (alive.current) setData((current) => ({ ...current, content }));
    } catch { if (alive.current) setError("Не удалось прочитать CSV в кодировке UTF-8."); }
    finally { if (alive.current) setBusy(false); }
  }

  async function execute(confirm: boolean) {
    if (busy || disabled || (confirm && !preview?.valid)) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/bank-statement/csv/${confirm ? "confirm" : "preview"}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(confirm ? { ...data, preview_digest: preview!.preview_digest } : data),
      });
      const result = await response.json();
      if (!alive.current) return;
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Проверьте файл и реквизиты импорта.");
      if (confirm) {
        setPreview(null);
        setMessage(`Обработано строк: ${result.count}. Проводки проверяются и подтверждаются в очереди ниже.`);
        await onImported();
      } else setPreview(result);
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "Ошибка импорта CSV."); }
    finally { if (alive.current) setBusy(false); }
  }

  return <details className="rounded-xl border border-border p-3">
    <summary className="cursor-pointer font-semibold">Загрузить выписку CSV</summary>
    <p className="my-2 text-sm text-muted">До 1000 операций BYN. UTF-8, разделитель — запятая. Направление: receipt — поступление, payment — списание; дата ГГГГ-ММ-ДД, сумма с точкой. Файл банка нужно привести к шаблону. Сохранение не создаёт проводки.</p>
    <a className="text-accent-ink underline" download="bank-statement-template.csv" href={`data:text/csv;charset=utf-8,${encodeURIComponent(template)}`}>Скачать шаблон CSV</a>
    <fieldset disabled={busy || disabled} className="my-3 grid gap-3 md:grid-cols-2">
      {([{ key: "provider", label: "Банк для CSV", max: 100 }, { key: "account_code", label: "Наш банковский счёт для CSV", max: 64 },
        { key: "evidence", label: "Основание принадлежности счёта для CSV", max: 1000 }] as const).map(({ key, label, max }) =>
        <label key={key}>{label}<Input aria-label={label} maxLength={max} value={data[key]}
          onChange={(event) => { setData({ ...data, [key]: event.target.value }); setPreview(null); setMessage(""); }} /></label>)}
      <label>Файл CSV<Input aria-label="Файл банковской выписки CSV" type="file" accept=".csv,text/csv" onChange={(event) => void readFile(event.target.files?.[0])} /></label>
    </fieldset>
    <Button disabled={busy || disabled || !org || !data.provider || !data.account_code || !data.evidence.trim() || !data.content} onClick={() => void execute(false)}>Проверить CSV</Button>
    {preview && <div className="my-3 space-y-2">
      <p>Корректных строк: {preview.valid_count}. Поступления: {preview.totals.receipt} BYN; списания: {preview.totals.payment} BYN.</p>
      {preview.errors.length > 0 && <div role="alert" className="max-h-64 overflow-auto text-red-700"><p>Импорт заблокирован. Исправьте все ошибки:</p>{preview.errors.map((item, i) => <p key={i}>Запись {item.record}: {item.message}</p>)}</div>}
      <Button disabled={busy || disabled || !preview.valid} onClick={() => void execute(true)}>Сохранить строки выписки</Button>
    </div>}
    {error && <p role="alert" className="mt-2 text-red-700">{error}</p>}
    {message && <p role="status" className="mt-2 text-money">{message}</p>}
  </details>;
}
