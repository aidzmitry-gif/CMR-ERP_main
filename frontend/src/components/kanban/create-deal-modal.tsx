"use client";

import { Search, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { fetchCrmStaff, fetchBuyerOptions, linkCrmClientToCounterparty, type BuyerOption, type CrmStaffMember, type DealInput } from "@/lib/api";
import type { Stage } from "@/lib/types";

const PRIORITIES = ["Высокий", "Средний", "Низкий"];
const INPUT = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
    </label>
  );
}

export function CreateDealModal({
  stages,
  defaultStage,
  onClose,
  onCreate,
  canAssignOwner = false,
  client,
}: {
  stages: Stage[];
  defaultStage: string;
  onClose: () => void;
  onCreate: (input: DealInput) => Promise<boolean>;
  /** Только admin/director/commercial: право подтверждает сервер, UI лишь не показывает реестр остальным. */
  canAssignOwner?: boolean;
  client?: { id: number; name: string; owner_id: number; counterparty_id?: number | null };
}) {
  const needsBuyer = !client || client.counterparty_id == null;
  const contextKey = `${client?.id ?? "new"}:${client?.counterparty_id ?? "unbound"}:${client?.owner_id ?? "self"}`;
  const currentContext = useRef(0);
  useLayoutEffect(() => {
    currentContext.current += 1;
    return () => { currentContext.current += 1; };
  }, [contextKey]);
  const previousContext = useRef(contextKey);
  const [form, setForm] = useState<DealInput>({
    number: "",
    counterparty: client?.name ?? "",
    ...(client ? { crm_client_id: client.id, owner_id: client.owner_id } : {}),
    title: "",
    amount: 0,
    priority: "Средний",
    stage: defaultStage,
    owner: "",
    next_step: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [directoryText, setDirectoryText] = useState("");
  const [directoryQuery, setDirectoryQuery] = useState("");
  const [directoryOffset, setDirectoryOffset] = useState(0);
  const [directoryRevision, setDirectoryRevision] = useState(0);
  const [directoryRows, setDirectoryRows] = useState<BuyerOption[]>([]);
  const [directoryNextOffset, setDirectoryNextOffset] = useState(0);
  const [directoryTotal, setDirectoryTotal] = useState(0);
  const [directoryStatus, setDirectoryStatus] = useState<"idle" | "loading" | "ok" | "error" | "unauthorized" | "forbidden">("loading");
  const [selected, setSelected] = useState<BuyerOption | null>(null);
  const directoryRequestId = useRef(0);
  const requestKey = useRef<string | null>(null);
  const [owners, setOwners] = useState<CrmStaffMember[] | null>(null);

  useEffect(() => {
    if (!needsBuyer) return;
    const controller = new AbortController();
    const requestId = directoryRequestId.current;
    let live = true;
    void fetchBuyerOptions(directoryQuery, directoryOffset, controller.signal).then((result) => {
      if (!live || requestId !== directoryRequestId.current) return;
      if (result.status !== "ok") {
        setDirectoryStatus(result.status);
        return;
      }
      setDirectoryRows((previous) => directoryOffset === 0 ? result.rows : [...previous, ...result.rows]);
      setDirectoryNextOffset(directoryOffset + result.rows.length);
      setDirectoryTotal(result.total);
      setDirectoryStatus("ok");
    });
    return () => { live = false; controller.abort(); };
  }, [contextKey, needsBuyer, directoryQuery, directoryOffset, directoryRevision]);

  useEffect(() => {
    if (previousContext.current === contextKey) return;
    previousContext.current = contextKey;
    directoryRequestId.current += 1;
    setSelected(null);
    setDirectoryText("");
    setDirectoryQuery("");
    setDirectoryOffset(0);
    setDirectoryRows([]);
    setDirectoryStatus("loading");
    setDirectoryRevision(value => value + 1);
    setSaving(false);
    setError(null);
    requestKey.current = null;
    setForm({ number: "", title: "", counterparty: client?.name ?? "", amount: 0,
      priority: "Средний", stage: defaultStage, owner: "", next_step: "",
      ...(client ? { crm_client_id: client.id, owner_id: client.owner_id } : {}) });
  }, [contextKey, client, defaultStage]);

  useEffect(() => {
    if (!canAssignOwner) return;
    let live = true;
    void fetchCrmStaff().then((staff) => {
      if (live) setOwners(staff);
    });
    return () => { live = false; };
  }, [canAssignOwner]);

  function set<K extends keyof DealInput>(key: K, value: DealInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function searchDirectory() {
    directoryRequestId.current += 1;
    setSelected(null);
    set("counterparty", client?.name ?? "");
    requestKey.current = null;
    setDirectoryRows([]);
    setDirectoryStatus("loading");
    setDirectoryOffset(0);
    setDirectoryQuery(directoryText.trim());
    setDirectoryRevision((value) => value + 1);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (saving) return;
    if (needsBuyer && !selected) {
      setError("Выберите контрагента из доступного справочника.");
      return;
    }
    if (!client && canAssignOwner && !form.owner_id) {
      setError("Выберите ответственного.");
      return;
    }
    const submittedContext = currentContext.current;
    setSaving(true);
    setError(null);
    try {
      let input = { ...form, ...(selected ? { counterparty_id: selected.id } : {}) };
      if (!client && selected) {
        requestKey.current ??= crypto.randomUUID();
        const linked = await linkCrmClientToCounterparty(
          selected.id, requestKey.current, form.owner_id ?? undefined,
        );
        if (currentContext.current !== submittedContext) return;
        if (!linked) {
          setError("Контрагент недоступен или не удалось создать связь с CRM. Обновите справочник и повторите.");
          return;
        }
        input = { ...form, counterparty: linked.name, crm_client_id: linked.id, owner_id: linked.owner_id, counterparty_id: selected.id };
      }
      if (currentContext.current !== submittedContext) return;
      const created = await onCreate(input);
      if (currentContext.current === submittedContext && !created) setError("Не удалось создать сделку (возможно, номер уже занят).");
    } catch {
      if (currentContext.current === submittedContext) setError("Не удалось создать сделку. Повторите попытку.");
    } finally {
      if (currentContext.current === submittedContext) setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onClick={() => { if (!saving) onClose(); }}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-2xl bg-surface p-5 shadow-pop"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-ink">Новая сделка</h3>
          <button type="button" onClick={onClose} disabled={saving} className="text-faint hover:text-muted disabled:opacity-50">
            <X size={20} />
          </button>
        </div>

        <fieldset disabled={saving} className="space-y-3">
          <Field label="Номер">
            <input required value={form.number} onChange={(e) => set("number", e.target.value)} placeholder="CRM-2024-0200" className={INPUT} />
          </Field>
          {needsBuyer && <div className="space-y-2">
            <Field label="Контрагент из справочника">
              <div className="flex gap-2">
                <input value={directoryText} maxLength={120} onChange={(e) => {
                  directoryRequestId.current += 1;
                  setDirectoryText(e.target.value);
                  setSelected(null);
                  set("counterparty", client?.name ?? "");
                  setDirectoryRows([]);
                  setDirectoryStatus("idle");
                  requestKey.current = null;
                }} placeholder="Название или УНП" className={INPUT} />
                <button type="button" onClick={searchDirectory}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-accent px-3 py-2 text-sm font-medium text-accent-ink hover:bg-accent-soft">
                  <Search size={15} /> Найти
                </button>
              </div>
            </Field>
            {directoryStatus === "loading" && <p role="status" className="text-xs text-muted">Загрузка контрагентов…</p>}
            {directoryStatus === "idle" && <p className="text-xs text-muted">Нажмите «Найти», чтобы показать результаты нового запроса.</p>}
            {directoryStatus !== "idle" && directoryStatus !== "loading" && directoryStatus !== "ok" &&
              <p role="alert" className="text-xs text-red-600">Справочник недоступен. Повторите поиск.</p>}
            {directoryStatus === "ok" && <>
              <ul aria-label="Доступные контрагенты" className="max-h-40 overflow-y-auto rounded-lg border border-line">
                {directoryRows.map((row) => <li key={row.id}>
                  <button type="button" aria-pressed={selected?.id === row.id}
                    onClick={() => { setSelected(row); if (!client) set("counterparty", row.name); requestKey.current = null; setError(null); }}
                    className="w-full border-b border-line px-3 py-2 text-left text-sm hover:bg-sunken aria-pressed:bg-accent-soft">
                    <span className="font-medium">{row.name}</span>
                    <span className="ml-2 text-xs text-muted">{row.unp ?? "без УНП"} · ID {row.id}</span>
                  </button>
                </li>)}
              </ul>
              {directoryRows.length === 0 && <p className="text-xs text-muted">Нет доступных контрагентов. Уточните поиск.</p>}
              {directoryNextOffset < directoryTotal && <button type="button" onClick={() => {
                directoryRequestId.current += 1;
                setDirectoryStatus("loading");
                setDirectoryOffset(directoryNextOffset);
              }}
                className="text-xs font-medium text-accent-ink underline">Показать ещё</button>}
            </>}
          </div>}
          <Field label="Компания">
            <input required readOnly disabled={Boolean(client)} value={form.counterparty}
              placeholder="Выберите контрагента выше" className={INPUT} />
          </Field>
          <Field label="Описание">
            <input required value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="Поставка ..." className={INPUT} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Сумма, BYN">
              <input type="number" min={0} value={form.amount} onChange={(e) => set("amount", Number(e.target.value))} className={INPUT} />
            </Field>
            <Field label="Приоритет">
              <select value={form.priority} onChange={(e) => set("priority", e.target.value)} className={INPUT}>
                {PRIORITIES.map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Стадия">
              <select disabled={Boolean(client)} value={form.stage} onChange={(e) => set("stage", e.target.value)} className={INPUT}>
                {client && <option value="new">Новая</option>}
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </Field>
            {canAssignOwner ? (
              <Field label="Ответственный">
                <select
                  aria-label="Ответственный"
                  disabled={Boolean(client)}
                  value={form.owner_id ?? ""}
                  onChange={(e) => { set("owner_id", e.target.value ? Number(e.target.value) : null); requestKey.current = null; }}
                  className={INPUT}
                >
                  <option value="">Не назначен</option>
                  {(owners ?? []).map((staff) => (
                    <option key={staff.employee_id} value={staff.employee_id}>{staff.full_name}</option>
                  ))}
                </select>
                {owners !== null && owners.length === 0 && (
                  <span className="mt-1 block text-xs text-faint">Список сотрудников недоступен</span>
                )}
              </Field>
            ) : (
              <Field label="Ответственный">
                <p className="rounded-lg border border-line bg-sunken px-3 py-2 text-sm text-muted">
                  {client ? "Ответственный клиента" : "Будет назначен автоматически после создания"}
                </p>
              </Field>
            )}
          </div>
        </fieldset>

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" disabled={saving} onClick={onClose} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-muted disabled:opacity-50">
            Отмена
          </button>
          <button type="submit" disabled={saving} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60">
            {saving ? "Сохранение..." : "Создать"}
          </button>
        </div>
      </form>
    </div>
  );
}
