"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

type Owner = { id: number; name: string };

export function CreateCrmClient({ onCreated, onCancel }: {
  onCreated: (name: string) => void; onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [unp, setUnp] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const [owners, setOwners] = useState<Owner[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const requestKey = useRef<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    void (async () => {
      try {
        const response = await fetch("/api/sales/clients/owners", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(response.status === 403 ? "Создание клиентов недоступно для вашей роли." : "Не удалось загрузить сотрудников.");
        const data: unknown = await response.json();
        if (!Array.isArray(data) || !data.every((o) => o && Number.isSafeInteger(o.id) && o.id > 0 && typeof o.name === "string")) {
          throw new Error("Не удалось загрузить сотрудников.");
        }
        if (current) {
          setOwners(data);
          if (data.length === 1) setOwnerId(String(data[0].id));
          setError(data.length ? "" : "Нет активного сотрудника CRM для назначения владельцем.");
        }
      } catch (failure) {
        if (current) setError(failure instanceof Error ? failure.message : "Не удалось загрузить сотрудников.");
      }
    })();
    return () => { current = false; controller.abort(); };
  }, [revision]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !name.trim() || !ownerId) return;
    setBusy(true);
    setError("");
    requestKey.current ??= crypto.randomUUID();
    try {
      const response = await fetch("/api/sales/clients", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), unp: unp.trim() || null,
          owner_id: Number(ownerId), request_key: requestKey.current }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "Не удалось создать клиента. Повторите попытку.");
      if (!data || !Number.isSafeInteger(data.id) || data.id <= 0 || data.source !== "crm" || typeof data.name !== "string") {
        throw new Error("Не удалось подтвердить создание клиента. Повторите попытку.");
      }
      if (mounted.current) onCreated(data.name);
    } catch (failure) {
      if (mounted.current) setError(failure instanceof Error ? failure.message : "Не удалось создать клиента. Повторите попытку.");
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return <form onSubmit={submit} aria-label="Новый клиент CRM" className="space-y-3 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold text-ink">Новый клиент</h2>
    <p className="text-sm text-muted">Клиент сохранится у выбранного менеджера. Сделку можно оформить позже.</p>
    <fieldset disabled={busy} className="grid gap-3 md:grid-cols-3">
      <label className="text-sm">Название клиента<input required maxLength={255} value={name}
        onChange={(event) => { setName(event.target.value); requestKey.current = null; }}
        className="mt-1 block h-10 w-full rounded-lg border border-line bg-surface px-3" /></label>
      <label className="text-sm">УНП (необязательно)<input maxLength={9} pattern="[0-9]{9}" value={unp}
        onChange={(event) => { setUnp(event.target.value); requestKey.current = null; }}
        className="mt-1 block h-10 w-full rounded-lg border border-line bg-surface px-3" /></label>
      <label className="text-sm">Ответственный<select value={ownerId}
        onChange={(event) => { setOwnerId(event.target.value); requestKey.current = null; }}
        className="mt-1 block h-10 w-full rounded-lg border border-line bg-surface px-3">
        <option value="">Выберите сотрудника</option>
        {owners?.map((owner) => <option key={owner.id} value={owner.id}>{owner.name}</option>)}
      </select></label>
    </fieldset>
    {!owners && !error && <p role="status">Загрузка сотрудников…</p>}
    {error && <div role="alert"><p>{error}</p>{!owners && <button type="button" className="underline"
      onClick={() => { setError(""); setRevision((value) => value + 1); }}>Повторить загрузку сотрудников</button>}</div>}
    <div className="flex gap-2">
      <button type="submit" disabled={busy || !ownerId || !name.trim()} className="rounded-lg bg-accent px-4 py-2 text-white disabled:opacity-50">{busy ? "Сохранение…" : "Создать клиента"}</button>
      <button type="button" disabled={busy} onClick={onCancel} className="rounded-lg border border-line px-4 py-2">Отмена</button>
    </div>
  </form>;
}
