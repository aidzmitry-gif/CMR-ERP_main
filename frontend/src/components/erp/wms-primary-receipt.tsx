"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Source = { organization_id: number; source_receipt_id: number; source_version: number; source_warehouse: string; lines: { position: number; sku: string; lot: string; quantity: string; unit: string }[] };
type Line = { position: number; sku_code: string; quantity: string };
type Command = { request_key: string; expected_version: number; warehouse: string; evidence: string; lines: Line[] };

export function WmsPrimaryReceipt({ org, receipt, version }: { org: string; receipt: string; version: string }) {
  const valid = [org, receipt, version].every(value => /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)));
  const [source, setSource] = useState<Source | null>(null);
  const [warehouse, setWarehouse] = useState(""), [evidence, setEvidence] = useState("");
  const [lines, setLines] = useState<Line[]>([]), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [frozen, setFrozen] = useState(false), [created, setCreated] = useState<number | null>(null);
  const pending = useRef<string | null>(null), running = useRef(false), active = useRef(true);
  const path = `/api/wms/organizations/${org}/primary-receipts/${receipt}`;
  const storageKey = `wms-primary-receipt:${org}:${receipt}:${version}`;
  useEffect(() => {
    active.current = true;
    const controller = new AbortController();
    if (valid) {
      let restored: Command | null = null;
      let recoveryFailed = false;
      try {
        const saved = sessionStorage.getItem(storageKey);
        if (saved) {
          const cmd: Command = JSON.parse(saved);
          if (cmd.expected_version !== Number(version) || !Array.isArray(cmd.lines) || typeof cmd.request_key !== "string") throw new Error("Не удалось восстановить команду приёмки.");
          pending.current = saved; restored = cmd;
        }
      } catch { recoveryFailed = true; }
      void fetch(`${path}/source?expected_version=${version}`, { cache: "no-store", signal: controller.signal }).then(async response => {
        if (!response.ok) throw new Error("Накладная недоступна для приёмки: проверьте версию, единицы и права склада.");
        const data: Source = await response.json();
        if (String(data.organization_id) !== org || String(data.source_receipt_id) !== receipt || String(data.source_version) !== version || !Array.isArray(data.lines)) throw new Error("Получена другая версия или организация.");
        if (!controller.signal.aborted) setSource(data);
      }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => {
        if (!controller.signal.aborted) {
          if (restored) { setFrozen(true); setWarehouse(restored.warehouse); setEvidence(restored.evidence); setLines(restored.lines); }
          if (recoveryFailed) { setSource(null); setError("Не удалось прочитать сохранённую команду приёмки."); }
        }
      });
    }
    return () => { active.current = false; controller.abort(); };
  }, [org, receipt, version, path, storageKey, valid]);
  function update(position: number, field: "sku_code" | "quantity", value: string) {
    setLines(current => [...current.filter(line => line.position !== position), { ...(current.find(line => line.position === position) ?? { position, sku_code: "", quantity: "" }), [field]: value }]);
  }
  async function submit() {
    if (running.current || created !== null) return;
    running.current = true; setBusy(true); setError("");
    try {
      if (!pending.current) {
        const selected = lines.filter(line => line.sku_code.trim() || line.quantity.trim());
        if (!source || !warehouse.trim() || !evidence.trim() || !selected.length || selected.some(line => !line.sku_code.trim() || !/^\d+(\.\d{1,2})?$/.test(line.quantity) || Number(line.quantity) <= 0)) throw new Error("Укажите склад, основание и точное количество хотя бы одной позиции.");
        const cmd: Command = { request_key: crypto.randomUUID(), expected_version: Number(version), warehouse: warehouse.trim(), evidence: evidence.trim(), lines: selected.map(line => ({ ...line, sku_code: line.sku_code.trim() })) };
        const body = JSON.stringify(cmd);
        sessionStorage.setItem(storageKey, body);
        pending.current = body; setFrozen(true);
      }
      const cmd: Command = JSON.parse(pending.current);
      const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: pending.current });
      if (!response.ok) {
        const failure = await response.json().catch(() => ({}));
        const rejected = response.status === 422 || (response.status === 409 && [
          "Select an existing warehouse SKU with the exact primary unit",
          "Physical receipts exceed the primary line quantity",
          "Primary receipt line does not exist",
          "Primary lot exceeds physical receipt storage; explicit mapping required",
        ].includes(failure.detail));
        if (rejected) {
          sessionStorage.removeItem(storageKey); pending.current = null;
          if (active.current) setFrozen(false);
          throw new Error("Команда отклонена до сохранения. Проверьте код номенклатуры, единицу и количество.");
        }
        throw new Error("Приёмка не подтверждена. Повторите ту же команду; при конфликте версии нужна сверка накладной.");
      }
      const result = await response.json();
      if (result.organization_id !== Number(org) || result.source_receipt_id !== Number(receipt) || result.source_version !== Number(version) || result.request_key !== cmd.request_key || !Number.isSafeInteger(result.receipt_id) || result.receipt_id < 1) throw new Error("Ответ приёмки не соответствует отправленной команде.");
      const stored = await fetch(`/api/wms/receipts/${result.receipt_id}`, { cache: "no-store" });
      if (!stored.ok) throw new Error("Не удалось проверить сохранённую приёмку. Повторите ту же команду.");
      const detail = await stored.json();
      if (detail.id !== result.receipt_id || detail.organization_id !== Number(org) || detail.entity_ref !== `procurement:receipt:${receipt}:${version}`) throw new Error("Сохранённая приёмка не соответствует накладной.");
      sessionStorage.removeItem(storageKey);
      if (active.current) setCreated(result.receipt_id);
    } catch (reason) { if (active.current) setError(reason instanceof Error ? reason.message : "Не удалось создать приёмку."); }
    finally { running.current = false; if (active.current) setBusy(false); }
  }
  if (!valid) return <p role="alert">Откройте подготовку приёмки из сохранённой накладной закупок.</p>;
  return <section className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h1 className="text-xl font-semibold">Приёмка по накладной № {receipt} · версия {version}</h1>
    <p>Юрлицо № {org}. Создаётся документ контроля качества; приход товара выполняется после QC.</p>
    {error && <p role="alert">{error}</p>}
    {frozen && !created && <p role="status">Команда сохранена в этой вкладке. Поля заблокированы для безопасного повтора.</p>}
    {source && <fieldset disabled={frozen || busy} className="space-y-3">
      <p>Склад в накладной: {source.source_warehouse}. Подтвердите склад физической приёмки.</p>
      <label>Склад приёмки<Input value={warehouse} onChange={e => setWarehouse(e.target.value)} /></label>
      <label>Основание сопоставления<Input value={evidence} onChange={e => setEvidence(e.target.value)} /></label>
      {source.lines.map(fact => <fieldset key={fact.position} className="rounded border border-line p-3"><legend>Строка {fact.position}: {fact.sku}</legend><p>Партия {fact.lot} · по накладной {fact.quantity} {fact.unit}</p>
        <label>Код складской номенклатуры<Input aria-label={`Складской SKU строки ${fact.position}`} value={lines.find(line => line.position === fact.position)?.sku_code ?? ""} onChange={e => update(fact.position, "sku_code", e.target.value)} /></label>
        <label>Количество к приёмке<Input aria-label={`Количество приёмки строки ${fact.position}`} value={lines.find(line => line.position === fact.position)?.quantity ?? ""} onChange={e => update(fact.position, "quantity", e.target.value)} /></label>
      </fieldset>)}
    </fieldset>}
    {!created && <Button disabled={busy || (!source && !frozen)} onClick={() => void submit()}>{busy ? "Сохраняется…" : frozen ? "Повторить ту же команду" : "Создать приёмку для QC"}</Button>}
    {created && <p role="status">Приёмка № {created} сохранена. <Link className="text-accent underline" href={`/erp/wms/receipts/${created}`}>Открыть контроль качества</Link></p>}
  </section>;
}
