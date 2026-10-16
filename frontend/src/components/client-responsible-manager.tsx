"use client";

import { useEffect, useRef, useState } from "react";
import { responsibleManagerText, validResponsibleManager, type ResponsibleManager } from "@/lib/crm-directory";

type Assignment = { client_id: number; revision: number; responsible_manager: ResponsibleManager | null; can_edit: boolean };
type Owner = { id: number; name: string };

function validAssignment(value: unknown, clientId: number): value is Assignment {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return row.client_id === clientId && row.source === "mdm" && Number.isSafeInteger(row.revision) && Number(row.revision) > 0
    && typeof row.can_edit === "boolean" && validResponsibleManager(row.responsible_manager);
}

export function ClientResponsibleManager({ clientId }: { clientId: number }) {
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState<{ key: string; data?: Assignment; error?: string } | null>(null);
  const [editing, setEditing] = useState(false);
  const [owners, setOwners] = useState<Owner[] | null>(null);
  const [employeeId, setEmployeeId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const generation = useRef(0);
  const key = `${clientId}:${revision}`;
  const state = loaded?.key === key ? loaded : null;
  const endpoint = `/api/sales/counterparties/${clientId}/responsible`;

  useEffect(() => {
    const controller = new AbortController();
    const operation = ++generation.current;
    void (async () => {
      try {
        const response = await fetch(endpoint, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(response.status === 401 ? "Сессия истекла. Войдите в ERP." : "Не удалось загрузить ответственного менеджера.");
        const data: unknown = await response.json();
        if (!validAssignment(data, clientId)) throw new Error("Сервер вернул некорректное назначение менеджера.");
        if (operation === generation.current) setLoaded({ key, data });
      } catch (failure) {
        if (operation === generation.current) setLoaded({ key, error: failure instanceof Error ? failure.message : "Ошибка загрузки менеджера." });
      }
    })();
    return () => { generation.current += 1; controller.abort(); };
  }, [clientId, endpoint, key]);

  useEffect(() => {
    if (!editing) return;
    const controller = new AbortController();
    let current = true;
    void (async () => {
      try {
        const response = await fetch("/api/sales/clients/owners", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error("Не удалось загрузить менеджеров CRM.");
        const data: unknown = await response.json();
        if (!Array.isArray(data) || !data.every((row) => row && Number.isSafeInteger(row.id) && row.id > 0 && typeof row.name === "string")) {
          throw new Error("Сервер вернул некорректный список менеджеров.");
        }
        if (current) setOwners(data);
      } catch (failure) {
        if (current) setError(failure instanceof Error ? failure.message : "Ошибка загрузки менеджеров.");
      }
    })();
    return () => { current = false; controller.abort(); };
  }, [editing]);

  async function save() {
    if (!state?.data || inFlight.current || !owners || (employeeId && !owners.some((row) => String(row.id) === employeeId))) return;
    inFlight.current = true; setBusy(true); setError("");
    const operation = generation.current;
    try {
      const response = await fetch(endpoint, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ employee_id: employeeId ? Number(employeeId) : null, expected_revision: state.data.revision }) });
      if (!response.ok) throw new Error(response.status === 409 ? "Карточка клиента изменилась. Обновите назначение и повторите выбор."
        : response.status === 403 ? "Нет права менять ответственного менеджера." : "Не удалось сохранить менеджера. Обновите назначение, чтобы проверить результат.");
      const data: unknown = await response.json();
      if (!validAssignment(data, clientId)) throw new Error("Не удалось проверить сохранённое назначение. Обновите его.");
      if (operation === generation.current) { setLoaded({ key, data }); setEditing(false); }
    } catch (failure) {
      if (operation === generation.current) setError(failure instanceof Error ? failure.message : "Ошибка сохранения менеджера.");
    } finally { inFlight.current = false; setBusy(false); }
  }

  return <section className="space-y-3 rounded-xl border border-line p-4" aria-label="Ответственный менеджер клиента">
    <h2 className="font-semibold">Ответственный менеджер</h2>
    {!state && <p role="status">Загрузка назначения…</p>}
    {state?.data && <p>{responsibleManagerText(state.data.responsible_manager)}</p>}
    {(state?.error || error) && <p role="alert">{state?.error || error}</p>}
    {state?.data?.can_edit && !editing && <button type="button" className="underline" onClick={() => {
      setEmployeeId(state.data?.responsible_manager ? String(state.data.responsible_manager.employee_id) : ""); setOwners(null); setError(""); setEditing(true);
    }}>{state.data.responsible_manager ? "Изменить менеджера" : "Назначить менеджера"}</button>}
    {editing && <div className="space-y-3">
      <label className="block text-sm">Менеджер CRM<select className="ml-2 rounded-lg border border-line p-2" value={employeeId} disabled={busy || !owners} onChange={(event) => setEmployeeId(event.target.value)}>
        <option value="">Не назначен</option>{owners?.map((row) => <option key={row.id} value={String(row.id)}>{row.name}</option>)}
      </select></label>
      {!owners && !error && <p role="status">Загрузка менеджеров…</p>}
      {owners?.length === 0 && <p>Нет активных менеджеров CRM. Проверьте карточки сотрудников и их доступы.</p>}
      <div className="flex gap-3"><button type="button" className="rounded-lg bg-accent px-3 py-2 text-white disabled:opacity-50" disabled={busy || !owners} onClick={() => void save()}>{busy ? "Сохранение…" : "Сохранить менеджера"}</button>
        <button type="button" className="underline" disabled={busy} onClick={() => { setEditing(false); setError(""); }}>Отмена</button></div>
      <p className="text-sm text-muted">Назначение менеджера не меняет права доступа и ответственных в существующих сделках.</p>
    </div>}
    <button type="button" disabled={busy} className="text-sm underline" onClick={() => {
      setEditing(false); setError(""); setOwners(null); setRevision((value) => value + 1);
    }}>Обновить назначение</button>
  </section>;
}
