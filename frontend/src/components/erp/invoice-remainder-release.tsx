"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { units, type Scope } from "@/lib/invoice-physical-shipment-api";
import { clearRemainder, loadRemainder, prepareRemainder, RemainderError, saveRemainder, submitRemainder, type RemainderRequest } from "@/lib/invoice-remainder-api";

export function InvoiceRemainderRelease({ scope, disabled, onLock, onReleased }: { scope: Scope; disabled: boolean; onLock: (locked: boolean) => void; onReleased: () => void }) {
  const [reason, setReason] = useState(""), [review, setReview] = useState<RemainderRequest | null>(null), [pending, setPending] = useState<RemainderRequest | null>(null);
  const [busy, setBusy] = useState(false), [ready, setReady] = useState(false), [storageFailed, setStorageFailed] = useState(false), [error, setError] = useState(""), [result, setResult] = useState<number | null>(null);
  const alive = useRef(true), lock = useRef(false);
  useEffect(() => {
    alive.current = true;
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      try { const saved = loadRemainder(scope); setPending(saved); onLock(!!saved); }
      catch { setStorageFailed(true); setError("Сохранённый запрос повреждён или недоступен. Новое снятие заблокировано до сверки."); onLock(true); }
      setReady(true);
    });
    return () => { alive.current = false; };
    // The enclosing shipment panel is keyed by the complete document scope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function prepare() {
    if (lock.current || disabled) return;
    lock.current = true; setBusy(true); onLock(true); setError("");
    try { const p = await prepareRemainder(scope, reason); if (alive.current) setReview(p); }
    catch (e) { if (alive.current) { setError(e instanceof Error ? e.message : "Не удалось рассчитать остаток."); onLock(false); } }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function submit(p: RemainderRequest) {
    if (lock.current || disabled) return;
    lock.current = true; setBusy(true); onLock(true); setError("");
    try {
      saveRemainder(p); setPending(p); setReview(null);
      const id = await submitRemainder(p);
      clearRemainder(p);
      if (alive.current) { setPending(null); setResult(id); onLock(false); onReleased(); }
    } catch (e) {
      if (alive.current) {
        setError(e instanceof Error ? e.message : "Результат снятия неизвестен.");
        if (e instanceof RemainderError && e.code === "remainder_basis_changed") {
          try { clearRemainder(p); setPending(null); setReview(null); onLock(false); }
          catch { setStorageFailed(true); }
        }
      }
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  const shown = pending ?? review;
  return <section aria-label="Снятие неотгруженного остатка" className="space-y-3 border-t border-line pt-4">
    <h3 className="font-semibold">Снять остаток резерва после частичной отгрузки</h3>
    <p className="text-sm text-muted">Освобождается весь неотгруженный резерв этого счёта. Физический остаток, счёт, оплаты и акты отгрузки сохраняются.</p>
    {error && <p role="alert">{error}</p>}
    {result && <p role="status">Остаток резерва снят. Квитанция № {result}.</p>}
    {!shown && !result && <><label className="block">Причина снятия остатка<textarea className="block w-full rounded border border-line p-2" maxLength={1000} value={reason} disabled={disabled || busy || storageFailed || !ready} onChange={e => setReason(e.target.value)} /></label><Button variant="secondary" disabled={disabled || busy || storageFailed || !ready || !reason.trim()} onClick={() => void prepare()}>Рассчитать снятие остатка</Button></>}
    {shown && <div className="space-y-3 rounded border border-line p-3"><p>{shown.body.evidence}</p><ul>{shown.basis.remaining.filter(row => units(row.qty) > BigInt(0)).map(row => <li key={row.source}>Строка {row.line_no} · {row.sku_code} · склад {row.warehouse} · снять {row.qty}</li>)}</ul>
      {pending && <p role="status">Запрос сохранён. Результат проверяется повтором с тем же ключом и причиной.</p>}
      <Button disabled={disabled || busy || storageFailed} onClick={() => void submit(shown)}>{pending ? "Проверить результат снятия тем же запросом" : "Подтвердить снятие остатка"}</Button>
      {!pending && <Button variant="secondary" disabled={busy} onClick={() => { setReview(null); onLock(false); }}>Вернуться к причине</Button>}
    </div>}
  </section>;
}
