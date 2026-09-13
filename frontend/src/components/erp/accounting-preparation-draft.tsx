"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

type Saved = { revision: number; draft: { organization_id: number; source: string; revision: number; request_key: string; payload: unknown; actor: string; created_at: string } | null };
export function AccountingPreparationDraft({ org, source, sourceKey, payload, disabled, onRestore, onBusy }: { org: string; source: string; sourceKey: string; payload: unknown; disabled: boolean; onRestore: (payload: unknown) => void; onBusy: (busy: boolean) => void }) {
  const [saved,setSaved] = useState<Saved | null>(null), [adopted,setAdopted] = useState(false);
  const [busy,setBusy] = useState(false), [error,setError] = useState(""), [notice,setNotice] = useState("");
  const pending = useRef<AbortController | null>(null);
  const command = useRef<{ fingerprint: string; body: { request_key: string; expected_revision: number; payload: unknown } } | null>(null);
  const endpoint = `/api/accounting/organizations/${org}/shipments/${sourceKey}/draft`;
  function checked(value: Saved) {
    if (!Number.isSafeInteger(value.revision) || value.revision < 0 || (value.draft ? String(value.draft.organization_id) !== org || value.draft.source !== source || value.draft.revision !== value.revision : value.revision !== 0)) throw new Error("Получен черновик другой операции или версии.");
    return value;
  }
  // Loading is explicit: reading a newer version must not silently authorize overwriting it.
  useEffect(() => () => pending.current?.abort(), []);
  async function load() {
    const controller = new AbortController(); pending.current?.abort(); pending.current = controller;
    setBusy(true); onBusy(true); setError(""); setNotice(""); setSaved(null); setAdopted(false);
    try {
      const response = await fetch(endpoint,{cache:"no-store",signal:controller.signal});
      if (!response.ok) throw new Error("Не удалось получить черновик. Проверьте доступ и повторите загрузку.");
      const data = checked(await response.json());
      if (!controller.signal.aborted) { setSaved(data); setAdopted(!data.draft); command.current = null; }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Ошибка загрузки."); }
    finally { if (!controller.signal.aborted) { setBusy(false); onBusy(false); } }
  }
  async function save() {
    if (!saved || !adopted || busy) return;
    const fingerprint = JSON.stringify({revision:saved.revision,payload});
    if (command.current?.fingerprint !== fingerprint) command.current = {fingerprint,body:{request_key:crypto.randomUUID(),expected_revision:saved.revision,payload}};
    const controller = new AbortController(); pending.current?.abort(); pending.current = controller;
    setBusy(true); onBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(command.current.body),signal:controller.signal});
      if (!response.ok) {
        if (response.status === 409) { setAdopted(false); throw new Error("Черновик изменён или акт уже проведён. Загрузите последнюю версию; ваши поля пока сохранены на экране."); }
        throw new Error("Сохранение не подтверждено. Повторите запрос без изменения полей или загрузите версию с сервера.");
      }
      const data = checked(await response.json());
      if (!data.draft || data.revision !== command.current.body.expected_revision + 1 || data.draft.request_key !== command.current.body.request_key) throw new Error("Ответ не подтверждает сохранение отправленного черновика. Повторите запрос или проверьте версию на сервере.");
      if (!controller.signal.aborted) { setSaved(data); setNotice(`Черновик версии ${data.revision} сохранён.`); command.current = null; }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Сохранение не подтверждено."); }
    finally { if (!controller.signal.aborted) { setBusy(false); onBusy(false); } }
  }
  return <section aria-label="Черновик подготовки" className="space-y-2 rounded border border-line p-3">
    <p>Черновик хранит введённые решения. Проводки и результат расчёта не сохраняются в нём.</p>
    <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={busy || disabled} onClick={() => void load()}>Проверить сохранённый черновик</Button>
      <Button variant="secondary" disabled={busy || disabled || !saved || !adopted} onClick={() => void save()}>Сохранить подготовку</Button>
      {saved?.draft && <Button variant="secondary" disabled={busy || disabled} onClick={() => { try { onRestore(saved.draft!.payload); setAdopted(true); setError(""); setNotice("Поля восстановлены. Проверьте дату, политику и выполните расчёт заново."); } catch (reason) { setError(reason instanceof Error ? reason.message : "Черновик не восстановлен."); } }}>Восстановить сохранённые поля</Button>}
    </div>
    {saved && <p>{saved.draft ? `Версия ${saved.revision} · ${saved.draft.actor} · ${saved.draft.created_at}` : "Сохранённого черновика нет."}</p>}
    {saved?.draft && !adopted && <p>Восстановление заменит поля на экране сохранённой версией. Сначала восстановите её, чтобы продолжить редактирование и сохранить новую версию.</p>}
    {busy && <p role="status">Обработка черновика…</p>}{notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
