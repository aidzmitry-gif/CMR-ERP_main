"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { AccountingClosingConfirm } from "./accounting-closing-confirm";

type Line = { account: string; side: string; amount: string; dimensions: Record<string, string> };
type Result = { organization_id: number; month: string; policy_id: number; status: string; confirmation_available: boolean; basis_digest?: string; period_generation?: number; monthly_lines: Line[]; annual_lines: Line[] };

export function AccountingClosingPreview({ org, month, evidence, onLock, onClosed }: { org: string; month: string; evidence?: Record<string, string>; onLock?: (locked: boolean) => void; onClosed?: (receiptId: number, currentlyClosed: boolean) => void | Promise<void> }) {
  const [data, setData] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [review, setReview] = useState<{ evidence: string; request_key: string } | null>(null);
  const evidenceKey = JSON.stringify(evidence ?? {});
  const [previousEvidence, setPreviousEvidence] = useState(evidenceKey);
  if (previousEvidence !== evidenceKey) {
    setPreviousEvidence(evidenceKey);
    if (!locked) setReview(null);
  }
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function calculate() {
    if (locked) return;
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setData(null); setError("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/financial-closing-preview`, { cache: "no-store", signal: controller.signal });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Проверьте настройки закрытия и права главного бухгалтера.");
      if (String(result.organization_id) !== org || result.month !== month || result.status !== "preview_only" || typeof result.confirmation_available !== "boolean" || !Array.isArray(result.monthly_lines) || !Array.isArray(result.annual_lines)) throw new Error("Расчёт не соответствует выбранному юрлицу и месяцу.");
      if (!controller.signal.aborted) { setData(result); setReview({ evidence: evidenceKey, request_key: crypto.randomUUID() }); }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Не удалось получить расчёт."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section aria-label="Расчёт финансового результата" className="space-y-3 rounded-lg border border-line p-3">
    <h3 className="font-semibold">Перенос финансового результата</h3>
    <p className="text-sm text-muted">Предварительный расчёт по настройкам учётной политики. Проводки не записываются, месяц не закрывается. Доступен главному бухгалтеру.</p>
    <Button variant="secondary" disabled={busy || locked || !/^\d{4}-\d{2}$/.test(month)} onClick={() => void calculate()}>{busy ? "Выполняется расчёт…" : "Рассчитать перенос финансового результата"}</Button>
    {error && <p role="alert">{error}</p>}
    {data && !data.confirmation_available && <p role="status">Закрытие недоступно: нормативная база учётной политики должна быть подтверждена главным бухгалтером.</p>}
    {data && <><p>Месяц: {data.month}. Версия политики: {data.policy_id}.</p>{([ ["Месячные проводки", data.monthly_lines], ["Годовые проводки", data.annual_lines] ] as const).map(([label, lines]) => <div key={label} className="max-w-full overflow-x-auto"><table className="w-full text-left text-sm"><caption className="text-left font-semibold">{label}</caption><thead><tr><th>Сторона</th><th>Счёт</th><th>Сумма, BYN</th><th>Аналитика</th></tr></thead><tbody>{lines.map((line, index) => <tr key={index} className="border-t border-line"><td>{line.side === "debit" ? "Дт" : "Кт"}</td><td>{line.account}</td><td>{line.amount}</td><td>{Object.entries(line.dimensions).map(([key,value]) => `${key}: ${value}`).join("; ") || "Без аналитики"}</td></tr>)}</tbody></table>{!lines.length && <p className="text-sm text-muted">Переносов по расчёту нет.</p>}</div>)}</>}
    {data?.confirmation_available && data.organization_id === Number(org) && data.month === month && review
      && (locked || review.evidence === evidenceKey) && evidence && onClosed
      && typeof data.basis_digest === "string" && /^[a-f0-9]{64}$/.test(data.basis_digest)
      && Number.isSafeInteger(data.period_generation) && (data.period_generation ?? -1) >= 0
      && ["documents","bank","settlements","stock","costing","depreciation","fx","tax","financial_result","trial_balance"].every(key => evidence[key]?.trim())
      && <AccountingClosingConfirm key={review.request_key} org={org} month={month}
        command={{ request_key: review.request_key, expected_basis_digest: data.basis_digest, expected_generation: data.period_generation!, evidence: JSON.parse(review.evidence) }}
        onLock={value => { setLocked(value); onLock?.(value); }} onClosed={onClosed} />}
    {data && !locked && (!review || review.evidence !== evidenceKey) && <p role="status">Основания проверок изменены. Повторите расчёт перед закрытием.</p>}
  </section>;
}
