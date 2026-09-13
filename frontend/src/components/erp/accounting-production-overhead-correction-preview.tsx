"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { sameOverheadCommand, validOverheadDate } from "@/lib/production-overhead-journal";
import type { PreparedOverhead } from "./accounting-production-overhead-confirmation";
import type { CorrectionPreviewCommand, PreparedCorrection } from "@/lib/production-correction-journal";
export type CorrectionTarget = { entryId: number; policyId: number; postingDate: string };
type Line = { account: string; side: "debit" | "credit"; amount: string; dimensions: Record<string, string> };
type Preview = { digest: string; snapshot: { organization_id: number; month: string; original_entry_id: number; command: unknown;
  status: string; posted: boolean; confirmation_available: boolean; final_cost_certified: boolean; creates_entry: boolean; correction_lines: Line[] } };
export function AccountingProductionOverheadCorrectionPreview({ org, month, target, prepared, disabled, onPrepared }: {
  org: string; month: string; target: CorrectionTarget; prepared: PreparedOverhead | null; disabled: boolean; onPrepared?: (value: PreparedCorrection | null) => void;
}) {
  const [date, setDate] = useState(""), [method, setMethod] = useState(""), [evidence, setEvidence] = useState("");
  const [result, setResult] = useState<Preview | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const earliest = [target.postingDate, prepared?.earliestDate ?? ""].sort().slice(-1)[0];
  const ready = !!prepared && method === "delta" && validOverheadDate(date, month) && date >= earliest && evidence.trim().length >= 10;
  function edit(action: () => void) { setResult(null); setError(""); onPrepared?.(null); action(); }
  async function calculate() {
    if (!ready || disabled || busy) return;
    const controller = new AbortController(); pending.current = controller; setBusy(true); setResult(null); setError("");
    onPrepared?.(null);
    const command: CorrectionPreviewCommand = { original_entry_id: target.entryId, review: prepared!.review, expected_review_digest: prepared!.digest,
      method: "delta", posting_date: date, evidence: evidence.trim() };
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/production-overhead-correction-preview`, {
        method: "POST", cache: "no-store", signal: controller.signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify(command) });
      if (!response.ok) throw new Error("Исправление не рассчитано. Проверьте актуальность источников, дату и открытость периода.");
      const data = await response.json() as Preview, s = data?.snapshot;
      if (!data || !/^[a-f0-9]{64}$/.test(data.digest) || String(s?.organization_id) !== org || s.month !== month
        || s.original_entry_id !== target.entryId || !sameOverheadCommand(s.command, command) || s.status !== "correction_preview"
        || s.posted !== false || typeof s.confirmation_available !== "boolean" || s.final_cost_certified !== false
        || !Array.isArray(s.correction_lines) || s.creates_entry !== (s.correction_lines.length > 0)
        || s.correction_lines.some(line => !line || typeof line.account !== "string" || !["debit", "credit"].includes(line.side)
          || typeof line.amount !== "string" || !/^\d+\.\d{2}$/.test(line.amount) || !line.dimensions || typeof line.dimensions !== "object"
          || Array.isArray(line.dimensions) || Object.values(line.dimensions).some(value => typeof value !== "string")))
        throw new Error("Расчёт не соответствует выбранному исправлению.");
      if (!controller.signal.aborted) { setResult(data); onPrepared?.(data.snapshot.confirmation_available
        ? { command, digest: data.digest, createsEntry: data.snapshot.creates_entry } : null); }
    } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="min-w-0 space-y-3 rounded border border-line p-2" aria-label="Расчёт исправления распределения">
    <h4 className="font-semibold">Исправление проводки №{target.entryId}</h4>
    {!prepared ? <p>Сначала проверьте состав затрат и пересчитайте целевое распределение.</p> : <fieldset className="min-w-0 space-y-2" disabled={disabled || busy}>
      <p>Сравнение с учтённой проводкой. Дата исправления в открытом месяце — не ранее {earliest}.</p>
      <label className="block">Метод исправления<Select aria-label="Метод исправления" value={method} onChange={e => edit(() => setMethod(e.target.value))}>
        <option value="">Выберите применимый метод</option><option value="delta">Разница сумм</option>
      </Select></label>
      <label className="block">Дата исправления<Input aria-label="Дата исправления" type="date" min={earliest} value={date} onChange={e => edit(() => setDate(e.target.value))} /></label>
      <label className="block">Основание исправления<textarea aria-label="Основание исправления" rows={4} maxLength={1000}
        className="w-full rounded border border-line bg-transparent p-2" value={evidence} onChange={e => edit(() => setEvidence(e.target.value))} /></label>
      <Button disabled={!ready} onClick={() => void calculate()}>Рассчитать разницу для исправления</Button>
    </fieldset>}
    {error && <p role="alert">{error}</p>}
    {result && <div role="status"><p>Предварительное исправление. В бухгалтерский учёт не записано.</p>
      {!result.snapshot.creates_entry && <p>Разница равна нулю; денежных проводок не требуется.</p>}
      {result.snapshot.correction_lines.map((line, i) => <p key={i}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.amount} BYN
        {Object.entries(line.dimensions).map(([key, value]) => ` · ${key === "department" ? "Подразделение" : key === "order" ? "Заказ" : key}: ${value}`)}</p>)}
    </div>}
  </section>;
}
