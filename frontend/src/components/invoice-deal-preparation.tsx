"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { DealClientBinding } from "./deal-client-binding";
import { fetchDocumentRegister, type DocumentRegisterPage } from "@/lib/document-register-api";
import { claimOwnership, clearOwnership, loadOwnership, ownershipCommand, OwnershipError, previewOwnership, saveOwnership,
  type OwnershipCommand, type OwnershipPreview } from "@/lib/deal-ownership-api";

type Props = { org: string; dealId: string; onReady: (ready: boolean) => void; onSelectOrg: (org: string) => void };
export function InvoiceDealPreparation(props: Props) {
  return <Preparation key={`${props.dealId}/${props.org}`} {...props} />;
}
function Preparation({ org, dealId, onReady, onSelectOrg }: Props) {
  const [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [owned, setOwned] = useState(false);
  const [preview, setPreview] = useState<OwnershipPreview | null>(null);
  const [readAttempted, setReadAttempted] = useState(false);
  const [pending, setPending] = useState<OwnershipCommand | null>(null);
  const [identity, setIdentity] = useState<DocumentRegisterPage["client_identity"] | null>(null);
  const [evidence, setEvidence] = useState(""), [error, setError] = useState("");
  const live = useRef(false), running = useRef(false), ready = useRef(onReady);
  useLayoutEffect(() => { ready.current = onReady; }, [onReady]);
  useLayoutEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      try { setPending(loadOwnership(dealId)); setLoaded(true); }
      catch (e) { setError((e as Error).message); }
    });
    return () => { active = false; };
  }, [dealId]);
  async function buyer() {
    const saved = loadOwnership(dealId);
    if (saved) { setPending(saved); setIdentity(null); return; }
    setIdentity(null);
    const page = await fetchDocumentRegister(org, dealId);
    if (live.current) { setOwned(true); setIdentity(page.client_identity); }
  }
  async function inspectExisting() {
    setReadAttempted(true); setPreview(null); setOwned(false);
    await buyer();
  }
  async function run(action: () => Promise<void>) {
    if (running.current) return;
    running.current = true; setBusy(true); setError(""); ready.current(false);
    try { await action(); }
    catch (e) { if (live.current) setError(e instanceof Error ? e.message : "Не удалось подготовить сделку."); }
    finally { running.current = false; if (live.current) setBusy(false); }
  }
  async function inspect() {
    if (!loaded) return;
    const saved = loadOwnership(dealId);
    if (saved) { setPending(saved); return; }
    setPreview(null); setIdentity(null); setOwned(false);
    const value = await previewOwnership(org, dealId);
    if (!live.current) return;
    setPreview(value); setOwned(value.assigned);
    if (value.assigned) await buyer();
  }
  async function confirm() {
    const stored = loadOwnership(dealId);
    if (stored && stored.org !== org) throw new OwnershipError("Вернитесь к организации исходного подтверждения.");
    const replaying = Boolean(stored);
    if (!stored && (!preview || preview.assigned)) throw new OwnershipError("Сначала проверьте принадлежность сделки.");
    const command = stored ?? ownershipCommand(org, dealId, preview!.snapshot, evidence);
    if (!stored) saveOwnership(command);
    setPending(command);
    try { await claimOwnership(command); }
    catch (e) {
      if (!replaying && e instanceof OwnershipError && e.status && e.status < 500 && !e.uncertain) {
        clearOwnership(dealId);
        if (live.current) { setPending(null); setPreview(null); }
      }
      throw e;
    }
    clearOwnership(dealId);
    if (!live.current) return;
    setPending(null); setOwned(true); setPreview(null);
    await buyer();
  }
  const foreign = pending && pending.org !== org;
  const pendingFacts = pending ? JSON.parse(pending.body) as { evidence: string; expected_snapshot: OwnershipPreview["snapshot"] } : null;
  return <section aria-label="Подготовка сделки к выпуску" className="my-3 space-y-3 rounded border border-line p-3">
    <h3 className="font-semibold">Подготовить сделку к выпуску</h3>
    <p>Проверьте подтверждённую организацию и покупателя сделки #{dealId}. Новую принадлежность подтверждает главный бухгалтер с доступом к сделке.</p>
    <a className="underline" href={`/crm/deals/${dealId}`} target="_blank" rel="noreferrer">Открыть созданную сделку #{dealId}</a>
    {error && <p role="alert">{error}</p>}
    {!loaded && !error && <p role="status">Проверяем сохранённый запрос…</p>}
    {pending && <div className="space-y-2">
      <p>Результат подтверждения организации #{pending.org} требует проверки. Новые факты не отправляются.</p>
      <p>Основание: {pendingFacts?.evidence}</p>
      <p>Сделка: {pendingFacts?.expected_snapshot.number} · {pendingFacts?.expected_snapshot.counterparty}.</p>
      {pendingFacts?.expected_snapshot.documents.map(d => <p key={d.id}>{d.kind} {d.number} · #{d.id} · версия {d.version} · сумма {d.amount}</p>)}
      {foreign ? <button onClick={() => onSelectOrg(pending.org)}>Вернуться к организации #{pending.org}</button>
        : <button disabled={busy} onClick={() => void run(confirm)}>Повторить исходное подтверждение организации</button>}
    </div>}
    {loaded && !pending && !owned && <>
      <button disabled={busy} onClick={() => void run(inspectExisting)}>Проверить принадлежность</button>
      {readAttempted && <div>
        <p>Если требуется новая привязка, главный бухгалтер может проверить её отдельно. Ошибка чтения не означает отсутствия принадлежности.</p>
        <button disabled={busy} onClick={() => void run(inspect)}>Подтвердить новую принадлежность</button>
      </div>}
    </>}
    {preview && !preview.assigned && !pending && <div className="space-y-2">
      <p>Организация #{org} · сделка {preview.snapshot.number} · #{preview.snapshot.deal_id} · {preview.snapshot.counterparty}</p>
      <p>Документы: {preview.snapshot.documents.length}. Подтверждённую организацию нельзя изменить этим действием.</p>
      {preview.snapshot.documents.map(d => <p key={d.id}>{d.kind} {d.number} · #{d.id} · версия {d.version} · сумма {d.amount}</p>)}
      <label className="block">Основание принадлежности организации<input aria-label="Основание принадлежности организации" className="block w-full rounded border p-2" value={evidence} maxLength={1000} disabled={busy} onChange={e => setEvidence(e.target.value)} /></label>
      <button disabled={busy || !evidence.trim()} onClick={() => void run(confirm)}>Подтвердить организацию сделки</button>
    </div>}
    {owned && !pending && <div className="space-y-2">
      <p>Организация #{org} подтверждена для сделки #{dealId}.</p>
      <button disabled={busy} onClick={() => void run(buyer)}>Проверить подтверждённого покупателя</button>
      {identity?.status === "unresolved" && <DealClientBinding org={org} dealId={dealId} onBound={() => void run(buyer)} />}
      {identity?.status === "confirmed" && <>
        <p>Покупатель: {identity.snapshot.name} · УНП {identity.snapshot.unp ?? "не указан"} · #{identity.counterparty_id}.</p>
        <button disabled={busy} onClick={() => ready.current(true)}>Продолжить к счёту</button>
      </>}
    </div>}
  </section>;
}
