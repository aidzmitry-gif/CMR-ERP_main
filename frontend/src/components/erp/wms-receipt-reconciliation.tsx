"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Organization = { id: number; name: string; unp: string };
type Receipt = { id: number; number: string; counterparty: string; warehouse: string; entity_ref: string };
type Detail = Receipt & { lines: { id: number; sku_code: string; sku_title: string; expected_qty: number | string }[] };
type Queue = { items: Receipt[]; next_after_id: number | null };
async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`/api/wms${path}`, { cache: "no-store", method: body ? "POST" : "GET", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (!response.ok) throw new Error(response.status === 403 ? "Нужны права главбуха выбранного юрлица и доступ к складу." : response.status === 404 || response.status === 409 ? "Документ изменился или уже сопоставлен. Обновите очередь." : "Не удалось загрузить или сохранить данные. Повторите запрос.");
  return response.json();
}

export function WmsReceiptReconciliation() {
  const [organizations, setOrganizations] = useState<Organization[]>([]), [org, setOrg] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    request<Organization[]>("/receipt-organizations").then((rows) => { if (active) setOrganizations(rows); }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  return <main className="min-w-0 w-0 flex-1 space-y-4 overflow-auto p-6 lg:pr-24">
    <h1 className="text-2xl font-semibold">Сопоставление приёмок</h1>
    <p className="text-sm text-muted">Общая очередь документов без владельца. Выбор юрлица не означает, что документы принадлежат ему. Проверьте первичные основания перед подтверждением. Уже принятые старые документы требуют отдельной сверки.</p>
    <label>Юрлицо для подтверждения<Select value={org} disabled={busy} onChange={(e) => setOrg(e.target.value)}><option value="">Выберите организацию</option>{organizations.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.unp}</option>)}</Select></label>
    {error && <p role="alert">{error}</p>}
    {org && <ReceiptQueue key={org} org={org} busy={busy} onBusy={setBusy} />}
  </main>;
}

function ReceiptQueue({ org, busy, onBusy }: { org: string; busy: boolean; onBusy: (value: boolean) => void }) {
  const [page, setPage] = useState<Queue | null>(null), [after, setAfter] = useState(0), [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<number | null>(null), [error, setError] = useState(""), [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    request<Queue>(`/receipts-unassigned?organization_id=${org}&after_id=${after}`).then((rows) => { if (active) setPage(rows); }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [org, after, reload]);
  function refresh(cursor = 0) { setSelected(null); setPage(null); setError(""); setAfter(cursor); setReload((value) => value + 1); }
  return <section className="space-y-3">
    <Button disabled={busy} onClick={() => refresh()}>Обновить очередь</Button>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!page && !error && <p role="status">Загрузка очереди…</p>}
    {page && <><ul className="divide-y divide-line rounded-lg border border-line">{page.items.map((row) => <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 p-3"><span>{row.number || `Приёмка № ${row.id}`} · {row.counterparty || "Контрагент не указан"} · {row.warehouse}</span><Button disabled={busy} onClick={() => { setSelected(row.id); setNotice(""); }}>Проверить № {row.id}</Button></li>)}</ul>{page.items.length === 0 && <p>Нет документов для сопоставления.</p>}{page.next_after_id !== null && <Button disabled={busy} onClick={() => refresh(page.next_after_id!)}>Следующие документы</Button>}</>}
    {selected !== null && <ReceiptAssignment key={selected} id={selected} org={org} busy={busy} onBusy={onBusy} onAssigned={() => { setNotice("Владелец подтверждён. Документ исключён из очереди."); refresh(); }} />}
  </section>;
}

function ReceiptAssignment({ id, org, busy, onBusy, onAssigned }: { id: number; org: string; busy: boolean; onBusy: (value: boolean) => void; onAssigned: () => void }) {
  const [detail, setDetail] = useState<Detail | null>(null), [evidence, setEvidence] = useState(""), [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    request<Detail>(`/receipts-unassigned/${id}?organization_id=${org}`).then((row) => { if (row.id !== id) throw new Error("Ответ относится к другой приёмке. Обновите очередь."); if (active) setDetail(row); }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [id, org]);
  async function confirm() {
    if (busy || !detail || !evidence.trim()) return;
    onBusy(true); setError("");
    try {
      const saved = await request<Detail & { organization_id: number }>(`/receipts/${id}/organization`, { organization_id: Number(org), evidence: evidence.trim() });
      if (saved.id !== id || saved.organization_id !== Number(org)) throw new Error("Ответ не подтверждает владельца этой приёмки. Обновите очередь перед повтором.");
      onAssigned();
    }
    catch (e) { setError(e instanceof Error ? e.message : "Не удалось подтвердить владельца."); }
    finally { onBusy(false); }
  }
  return <section aria-label="Проверка владельца приёмки" className="space-y-3 rounded-lg border border-line p-4">
    {error && <p role="alert">{error}</p>}
    {!detail && !error && <p>Загрузка документа…</p>}
    {detail && <><h2 className="text-lg font-semibold">{detail.number || `Приёмка № ${id}`}</h2><p>Основание: {detail.entity_ref || "Не указано"}</p><ul>{detail.lines.map((line) => <li key={line.id}>{line.sku_code} · {line.sku_title} · {line.expected_qty}</li>)}</ul><label>Основание принадлежности<Input value={evidence} maxLength={1000} disabled={busy} onChange={(e) => setEvidence(e.target.value)} /></label><Button disabled={busy || !evidence.trim()} onClick={() => void confirm()}>Подтвердить владельца</Button></>}
  </section>;
}
