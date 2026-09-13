"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { shipmentValidationMessage } from "@/lib/shipment-validation-message";

export function AccountingShipmentConfirm({ org, sourceKey, source, body, onLock, onPosted }: {
  org: string; sourceKey: string; source: string; body: string; onLock: (locked: boolean) => void;
  onPosted?: () => void | Promise<void>;
}) {
  const [state, setState] = useState<"ready" | "sending" | "uncertain" | "done" | "rejected">("ready");
  const [message, setMessage] = useState("");
  const postedCallback = useRef(onPosted);
  useEffect(() => { postedCallback.current = onPosted; }, [onPosted]);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function confirm() {
    if (state === "sending" || state === "done" || state === "rejected") return;
    setState("sending"); onLock(true); setMessage("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/shipments/${sourceKey}/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body,
      });
      const value = await response.json();
      if (!response.ok) {
        if ([401, 403, 404, 409, 422].includes(response.status)) {
          setState("rejected"); onLock(false);
          setMessage(shipmentValidationMessage(value.detail) + " Выполните новый расчёт перед подтверждением.");
          return;
        }
        throw new Error("Uncertain server result");
      }
      if (value.organization_id !== Number(org) || value.source !== source || value.posted !== true
        || value.basis_digest !== JSON.parse(body).expected_basis_digest
        || !Number.isSafeInteger(value.receipt_id) || value.receipt_id <= 0
        || !Array.isArray(value.entry_ids) || !value.entry_ids.length
        || !value.entry_ids.every((id: unknown) => typeof id === "number" && Number.isSafeInteger(id) && id > 0)) {
        throw new Error("Unverified confirmation");
      }
      setState("done"); onLock(false);
      setMessage(`Отгрузка проведена. Проводки: ${value.entry_ids.join(", ")}. Обновите журнал и отчёты.`);
    } catch {
      setState("uncertain");
      setMessage("Ответ не подтверждён. Повторите тот же запрос: сервер вернёт исходный пакет без повторного списания.");
      return;
    }
    // Refresh failures cannot turn an acknowledged posting into an uncertain write.
    if (mounted.current) {
      try { await postedCallback.current?.(); }
      catch { setMessage("Отгрузка проведена. Не удалось обновить данные: нажмите «Обновить»."); }
    }
  }
  return <section aria-label="Подтверждение проводок отгрузки" className="space-y-2">
    <p>Подтверждается весь показанный пакет проводок по отгрузке.</p>
    {message && <p role={state === "done" ? "status" : "alert"}>{message}</p>}
    {state !== "done" && state !== "rejected" && <Button disabled={state === "sending"} onClick={() => void confirm()}>
      {state === "uncertain" ? "Повторить подтверждение" : state === "sending" ? "Проводим…" : "Подтвердить проводки отгрузки"}
    </Button>}
  </section>;
}
