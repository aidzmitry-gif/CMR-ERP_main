"use client";

import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  lookupCounterpartyResult,
  type RegistryInfo,
} from "@/lib/api";
import {
  createCounterparty,
  type CounterpartyCard,
  type CounterpartyRegistryField,
  type CounterpartySaveResult,
  type CounterpartyWriteInput,
  updateCounterparty,
} from "@/lib/reference-data";
import { formatAuditDate, sourceMeta } from "@/lib/spravochniki-card";

type RegistryField = CounterpartyRegistryField;
type ManualField = "name" | "unp" | "legal_address" | "registry_status" | "bank_name" | "bank_account" | "bank_bic";

const REGISTRY_FIELDS: RegistryField[] = ["name", "unp", "legal_address", "registry_status"];
const REGISTRY_LABELS: Record<RegistryField, string> = {
  name: "Наименование",
  unp: "УНП",
  legal_address: "Юридический адрес",
  registry_status: "Статус реестра",
};
const MANUAL_FIELDS: ManualField[] = [
  "name",
  "unp",
  "legal_address",
  "registry_status",
  "bank_name",
  "bank_account",
  "bank_bic",
];

type ReturnQuery = { name?: string; unp?: string };

type CreateProps = {
  mode: "create";
  card?: never;
  initialUnp?: string;
  returnQuery?: ReturnQuery;
  onCancel?: () => void;
  embedded?: boolean;
};

type EditProps = {
  mode: "edit";
  card: CounterpartyCard;
  returnQuery?: ReturnQuery;
  onCancel?: () => void;
  embedded?: boolean;
};

export type SpravCounterpartyEditorProps = CreateProps | EditProps;

type DraftContact = {
  key: string;
  id?: number;
  full_name: string;
  phone: string;
  email: string;
  is_primary: boolean;
};

type Draft = {
  name: string;
  unp: string;
  legal_address: string;
  registry_status: string;
  bank_name: string;
  bank_account: string;
  bank_bic: string;
  contacts: DraftContact[];
};

type Preview = {
  data: RegistryInfo;
  values: Record<RegistryField, string>;
};

function text(value: string | null | undefined): string {
  return value ?? "";
}

function draftFromCard(card: CounterpartyCard): Draft {
  const requisites = card.requisites ?? {};
  return {
    name: card.name,
    unp: text(card.unp),
    legal_address: text(requisites.legal_address),
    registry_status: text(requisites.registry_status),
    bank_name: text(requisites.bank_name),
    bank_account: text(requisites.bank_account),
    bank_bic: text(requisites.bank_bic),
    contacts: card.contacts.map((contact) => ({
      key: `existing-${contact.id}`,
      id: contact.id,
      full_name: contact.full_name,
      phone: text(contact.phone),
      email: text(contact.email),
      is_primary: contact.is_primary,
    })),
  };
}

function emptyDraft(initialUnp = ""): Draft {
  return {
    name: "",
    unp: initialUnp,
    legal_address: "",
    registry_status: "",
    bank_name: "",
    bank_account: "",
    bank_bic: "",
    contacts: [],
  };
}

function valuesFromRegistry(data: RegistryInfo): Record<RegistryField, string> {
  return {
    name: data.name,
    unp: data.unp,
    legal_address: data.address,
    registry_status: data.status,
  };
}

function currentValue(draft: Draft, field: RegistryField): string {
  return draft[field];
}

function queryHref(id: number, query?: ReturnQuery): string {
  const params = new URLSearchParams();
  if (query?.name) params.set("name", query.name);
  if (query?.unp) params.set("unp", query.unp);
  const encoded = params.toString();
  return `/erp/spravochniki/counterparty/${encodeURIComponent(String(id))}${encoded ? `?${encoded}` : ""}`;
}

function normalize(value: string): string {
  return value.trim();
}

function resultMessage(result: Exclude<CounterpartySaveResult, { status: "success" }>): string {
  switch (result.status) {
    case "unauthorized":
      return "Сессия истекла или отсутствует авторизация (401). Введённые данные оставлены в форме.";
    case "forbidden":
      return "Нет права изменять карточку (403). Введённые данные оставлены в форме.";
    case "conflict": {
      const message = result.message || "Карточка уже изменена";
      return result.code === "duplicate_unp"
        ? `${message} Найдите карточку по УНП и используйте её.`
        : message;
    }
    case "validation-error":
      return result.message || "Проверьте введённые реквизиты.";
    case "not-found":
      return result.message || "Карточка не найдена. Введённые данные оставлены в форме.";
    case "service-error":
      return result.message || "Сервис сохранения недоступен. Введённые данные оставлены в форме.";
  }
}

function contactPayload(contact: DraftContact, includeId: boolean) {
  return {
    ...(includeId && contact.id ? { id: contact.id } : {}),
    full_name: normalize(contact.full_name),
    phone: normalize(contact.phone) || null,
    email: normalize(contact.email) || null,
    is_primary: contact.is_primary,
  };
}

export function SpravCounterpartyEditor(props: SpravCounterpartyEditorProps) {
  const router = useRouter();
  const isEdit = props.mode === "edit";
  const card = isEdit ? props.card : undefined;
  const canEdit = !isEdit || Boolean(
    card && card.is_active && card.merged_into_id === null && card.revision && card.revision > 0,
  );
  const initialUnp = props.mode === "create" ? props.initialUnp ?? "" : "";
  const initialDraft = useMemo(
    () => (isEdit && card ? draftFromCard(card) : emptyDraft(initialUnp)),
    [card, initialUnp, isEdit],
  );
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [savedDraft, setSavedDraft] = useState<Draft>(initialDraft);
  const [editing, setEditing] = useState(!isEdit && canEdit);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveNotice, setSaveNotice] = useState("");
  const [lookupState, setLookupState] = useState<"idle" | "loading" | "found" | "error">("idle");
  const [lookupError, setLookupError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selectedFields, setSelectedFields] = useState<Set<RegistryField>>(new Set());
  const [lastSavedRevision, setLastSavedRevision] = useState<number | null>(null);
  const lookupVersion = useRef(0);
  const previousCardId = useRef(card?.id);
  const baselineRevision = useRef(card?.revision);
  const previousRevision = useRef(card?.revision);
  const saveLatch = useRef(false);
  const contactSequence = useRef(0);

  useEffect(() => {
    if (!isEdit || !card) return;
    const identityChanged = previousCardId.current !== card.id;
    const revisionChanged = previousRevision.current !== card.revision;
    previousCardId.current = card.id;
    previousRevision.current = card.revision;
    // A background refresh must not replace a dirty form or advance the
    // expected revision while the user is editing. A new identity is safe to
    // adopt immediately; a changed revision is adopted only while collapsed.
    if (!identityChanged && (!revisionChanged || editing)) return;
    const nextDraft = draftFromCard(card);
    baselineRevision.current = card.revision;
    setDraft(nextDraft);
    setSavedDraft(nextDraft);
    setLastSavedRevision((current) => (
      current !== null && card.revision !== undefined && card.revision >= current ? null : current
    ));
    setPreview(null);
    setSelectedFields(new Set());
    setSaveError("");
    setSaveNotice("");
  }, [card, editing, isEdit]);

  function updateField(field: ManualField, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
    if (REGISTRY_FIELDS.includes(field as RegistryField)) {
      setSelectedFields((current) => {
        const next = new Set(current);
        next.delete(field as RegistryField);
        return next;
      });
    }
    if (field === "unp") {
      lookupVersion.current += 1;
      setPreview(null);
      setSelectedFields(new Set());
      setLookupState("idle");
      setLookupError("");
    }
    setSaveError("");
    setSaveNotice("");
  }

  async function lookup() {
    const unp = normalize(draft.unp);
    const version = ++lookupVersion.current;
    setLookupState("loading");
    setLookupError("");
    setPreview(null);
    setSelectedFields(new Set());
    const result = await lookupCounterpartyResult(unp);
    if (lookupVersion.current !== version || normalize(draft.unp) !== unp) return;
    if (result.status !== "found") {
      setLookupState("error");
      setLookupError(result.message);
      return;
    }
    setLookupState("found");
    setPreview({ data: result.data, values: valuesFromRegistry(result.data) });
  }

  function toggleRegistryField(field: RegistryField) {
    setSelectedFields((current) => {
      const next = new Set(current);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
    setSaveError("");
    setSaveNotice("");
  }

  function addContact() {
    contactSequence.current += 1;
    setDraft((current) => ({
      ...current,
      contacts: [
        ...current.contacts,
        {
          key: `new-${contactSequence.current}`,
          full_name: "",
          phone: "",
          email: "",
          is_primary: false,
        },
      ],
    }));
  }

  function updateContact(key: string, field: keyof Omit<DraftContact, "key" | "id">, value: string | boolean) {
    setDraft((current) => ({
      ...current,
      contacts: current.contacts.map((contact) =>
        contact.key === key ? { ...contact, [field]: value } : contact,
      ),
    }));
    setSaveError("");
    setSaveNotice("");
  }

  function removeNewContact(key: string) {
    setDraft((current) => ({
      ...current,
      contacts: current.contacts.filter((contact) => contact.key !== key || contact.id),
    }));
  }

  function validate(): string | null {
    const selectedPreview = preview && selectedFields.size > 0 ? preview : null;
    const effectiveName = selectedPreview && selectedFields.has("name")
      ? selectedPreview.values.name
      : normalize(draft.name);
    const effectiveUnp = selectedPreview && selectedFields.has("unp")
      ? selectedPreview.values.unp
      : normalize(draft.unp);
    if (!effectiveName) return "Укажите название компании или выберите его из предпросмотра.";
    if (effectiveUnp && !/^\d{9}$/.test(effectiveUnp)) return "УНП должен содержать 9 цифр.";
    if (isEdit && selectedFields.has("unp") && card?.unp && preview?.values.unp !== card.unp) {
      return "Смена УНП существующей карточки через реестр запрещена. Измените УНП вручную без выбора поля реестра.";
    }
    for (const contact of draft.contacts) {
      if (!contact.id && !normalize(contact.full_name)) return "Укажите имя нового контактного лица или удалите строку.";
      if (normalize(contact.email) && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalize(contact.email))) {
        return "Проверьте email контактного лица.";
      }
      if (normalize(contact.phone) && !/\d/.test(contact.phone)) return "Телефон должен содержать цифры.";
    }
    if (normalize(draft.bank_bic) && !/^[A-Za-z]{6}[A-Za-z0-9]{2}(?:[A-Za-z0-9]{3})?$/.test(normalize(draft.bank_bic))) {
      return "BIC должен содержать 8 или 11 допустимых символов.";
    }
    return null;
  }

  function buildPayload(): CounterpartyWriteInput {
    const manual: Record<string, string | null> = {};
    const selected = selectedFields;
    for (const field of MANUAL_FIELDS) {
      if (selected.has(field as RegistryField)) continue;
      const value = normalize(draft[field]);
      const initialValue = normalize(savedDraft[field]);
      if (!isEdit) {
        if (value) manual[field] = value;
      } else if (value !== initialValue) {
        manual[field] = value || null;
      }
    }

    const contacts = draft.contacts.flatMap((contact) => {
      if (!isEdit) return [contactPayload(contact, false)];
      const initial = savedDraft.contacts.find((item) => item.id === contact.id);
      if (!initial) return [contactPayload(contact, false)];
      if (
        contact.full_name === initial.full_name &&
        contact.phone === initial.phone &&
        contact.email === initial.email &&
        contact.is_primary === initial.is_primary
      ) return [];
      return [contactPayload(contact, true)];
    });

    const payload: CounterpartyWriteInput = {};
    if (Object.keys(manual).length > 0) payload.manual = manual as CounterpartyWriteInput["manual"];
    if (contacts.length > 0) payload.contacts = contacts;
    if (preview && selected.size > 0) {
      const fields = REGISTRY_FIELDS.filter((field) => selected.has(field));
      payload.registry = {
        unp: preview.data.unp,
        fields,
        preview: Object.fromEntries(fields.map((field) => [field, preview.values[field]])) as Partial<Record<RegistryField, string>>,
      };
    }
    if (isEdit && baselineRevision.current) payload.expected_revision = baselineRevision.current;
    return payload;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || saveLatch.current) return;
    const validationError = validate();
    if (validationError) {
      setSaveError(validationError);
      return;
    }
    if (isEdit && !card?.revision) {
      setSaveError("У карточки нет подтверждённой версии. Редактирование отключено.");
      return;
    }
    if (isEdit && !baselineRevision.current) {
      setSaveError("У карточки нет подтверждённой версии. Редактирование отключено.");
      return;
    }
    saveLatch.current = true;
    setBusy(true);
    setSaveError("");
    setSaveNotice("");
    const payload = buildPayload();
    const result = isEdit && card
      ? await updateCounterparty(card.id, payload as CounterpartyWriteInput & { expected_revision: number })
      : await createCounterparty(payload);
    if (result.status !== "success") {
      setBusy(false);
      saveLatch.current = false;
      setSaveError(resultMessage(result));
      return;
    }
    lookupVersion.current += 1;
    setPreview(null);
    setSelectedFields(new Set());
    setLookupState("idle");
    setLookupError("");
    if (!isEdit) {
      router.push(queryHref(result.id, props.returnQuery));
      return;
    }
    setBusy(false);
    saveLatch.current = false;
    baselineRevision.current = result.revision;
    setLastSavedRevision(result.revision);
    setSavedDraft(draft);
    setSaveNotice(`Сохранено. Версия карточки: ${result.revision}.`);
    setEditing(false);
    router.refresh();
  }

  function cancel() {
    if (saveLatch.current) return;
    lookupVersion.current += 1;
    setDraft(savedDraft);
    setPreview(null);
    setSelectedFields(new Set());
    setLookupState("idle");
    setLookupError("");
    setSaveError("");
    setSaveNotice("");
    if (isEdit) setEditing(false);
    props.onCancel?.();
  }

  function refreshCard() {
    if (busy || saveLatch.current) return;
    if (isEdit && card) {
      const nextDraft = draftFromCard(card);
      baselineRevision.current = card.revision;
      previousRevision.current = card.revision;
      setDraft(nextDraft);
      setSavedDraft(nextDraft);
      setPreview(null);
      setSelectedFields(new Set());
      setSaveError("");
      setSaveNotice("");
      setEditing(false);
    }
    router.refresh();
  }

  const title = isEdit ? "Редактирование контрагента" : "Новый контрагент";
  const readOnlyReason = card && !card.is_active
    ? "Архивная карточка доступна только для чтения."
    : card?.merged_into_id
      ? "Карточка объединена с другой записью и доступна только для чтения."
      : "У карточки нет подтверждённой версии для безопасного изменения.";
  const waitingForFreshCard = isEdit && lastSavedRevision !== null;
  const containerClass = props.embedded
    ? "min-w-0 space-y-4"
    : "mx-auto min-w-0 max-w-5xl space-y-4 px-6 pb-6 pr-[74px] lg:pr-6";

  return (
    <section className={containerClass} aria-label={title}>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-2xl bg-surface p-5 shadow-card">
        <div className="min-w-0">
          <h2 className="text-lg font-bold text-ink">{title}</h2>
          {isEdit && card && (
            <p className="mt-1 break-words text-xs text-muted">
              #{card.id} · версия {card.revision ?? "не подтверждена"}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isEdit && canEdit && (
            <button
              type="button"
              disabled={busy || waitingForFreshCard}
              onClick={() => {
                if (waitingForFreshCard) return;
                setEditing((current) => !current);
              }}
              className="rounded-xl border border-line px-3 py-2 text-sm font-medium text-ink hover:bg-sunken"
            >
              {waitingForFreshCard
                ? "Ожидание обновления…"
                : editing ? "Свернуть редактор" : "Редактировать"}
            </button>
          )}
          {isEdit && (
            <button
              type="button"
              disabled={busy}
              onClick={refreshCard}
              className="rounded-xl border border-line px-3 py-2 text-sm font-medium text-muted hover:bg-sunken"
            >
              Обновить карточку
            </button>
          )}
        </div>
      </div>

      {!canEdit && (
        <p className="rounded-2xl bg-surface p-5 text-sm text-muted shadow-card" role="status">
          {readOnlyReason}
        </p>
      )}

      {canEdit && editing && (
        <form className="min-w-0 space-y-4" onSubmit={submit}>
          <fieldset disabled={busy} className="min-w-0 space-y-4">
          <div className="rounded-2xl bg-surface p-5 shadow-card">
            <div className="grid min-w-0 gap-3 sm:grid-cols-2">
              <label className="min-w-0 text-sm text-muted">
                Наименование
                <input
                  className="mt-1 w-full min-w-0 rounded-xl border border-line bg-sunken px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
                  value={draft.name}
                  onChange={(event) => updateField("name", event.target.value)}
                  aria-label="Наименование компании"
                />
              </label>
              <label className="min-w-0 text-sm text-muted">
                УНП
                <div className="mt-1 flex min-w-0 flex-col gap-2 sm:flex-row">
                  <input
                    className="w-full min-w-0 rounded-xl border border-line bg-sunken px-3 py-2 font-mono text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20 sm:flex-1"
                    value={draft.unp}
                    onChange={(event) => updateField("unp", event.target.value)}
                    inputMode="numeric"
                    aria-label="УНП (карточка)"
                  />
                  <button
                    type="button"
                    disabled={busy || lookupState === "loading"}
                    onClick={() => void lookup()}
                    className="w-full rounded-xl border border-line px-3 py-2 text-sm font-medium text-accent-ink hover:bg-accent-soft disabled:cursor-wait disabled:opacity-50 sm:w-auto"
                  >
                    {lookupState === "loading" ? "Получаю…" : "Получить по УНП"}
                  </button>
                </div>
              </label>
              <label className="min-w-0 text-sm text-muted sm:col-span-2">
                Юридический адрес
                <input
                  className="mt-1 w-full min-w-0 rounded-xl border border-line bg-sunken px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
                  value={draft.legal_address}
                  onChange={(event) => updateField("legal_address", event.target.value)}
                  aria-label="Юридический адрес"
                />
              </label>
              <label className="min-w-0 text-sm text-muted">
                Статус реестра
                <input
                  className="mt-1 w-full min-w-0 rounded-xl border border-line bg-sunken px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
                  value={draft.registry_status}
                  onChange={(event) => updateField("registry_status", event.target.value)}
                  aria-label="Статус реестра"
                />
              </label>
            </div>
          </div>

          <div className="rounded-2xl bg-surface p-5 shadow-card">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">Банковские реквизиты</p>
            <div className="mt-4 grid min-w-0 gap-3 sm:grid-cols-2">
              <label className="min-w-0 text-sm text-muted">
                Банк
                <input
                  className="mt-1 w-full min-w-0 rounded-xl border border-line bg-sunken px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
                  value={draft.bank_name}
                  onChange={(event) => updateField("bank_name", event.target.value)}
                  aria-label="Банк"
                />
              </label>
              <label className="min-w-0 text-sm text-muted">
                Счёт IBAN
                <input
                  className="mt-1 w-full min-w-0 rounded-xl border border-line bg-sunken px-3 py-2 font-mono text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
                  value={draft.bank_account}
                  onChange={(event) => updateField("bank_account", event.target.value)}
                  aria-label="Счёт IBAN"
                />
              </label>
              <label className="min-w-0 text-sm text-muted sm:col-span-2">
                BIC
                <input
                  className="mt-1 w-full min-w-0 rounded-xl border border-line bg-sunken px-3 py-2 font-mono text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
                  value={draft.bank_bic}
                  onChange={(event) => updateField("bank_bic", event.target.value)}
                  aria-label="BIC"
                />
              </label>
            </div>
          </div>

          <div className="rounded-2xl bg-surface p-5 shadow-card">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">Контакты</p>
              <button
                type="button"
                onClick={addContact}
                className="rounded-xl border border-line px-3 py-2 text-sm font-medium text-accent-ink hover:bg-accent-soft"
              >
                + Добавить контакт
              </button>
            </div>
            {draft.contacts.length === 0 ? (
              <p className="mt-3 text-sm text-muted">Контактов пока нет.</p>
            ) : (
              <div className="mt-4 min-w-0 space-y-3">
                {draft.contacts.map((contact, index) => (
                  <div key={contact.key} className="min-w-0 rounded-xl bg-sunken p-3">
                    <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                      <label className="min-w-0 text-sm text-muted">
                        Имя контакта
                        <input
                          className="mt-1 w-full min-w-0 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                          value={contact.full_name}
                          onChange={(event) => updateContact(contact.key, "full_name", event.target.value)}
                          aria-label={`Имя контакта ${index + 1}`}
                        />
                      </label>
                      <label className="min-w-0 text-sm text-muted">
                        Телефон
                        <input
                          className="mt-1 w-full min-w-0 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                          value={contact.phone}
                          onChange={(event) => updateContact(contact.key, "phone", event.target.value)}
                          aria-label={`Телефон контакта ${index + 1}`}
                        />
                      </label>
                      <label className="min-w-0 text-sm text-muted">
                        Email
                        <input
                          className="mt-1 w-full min-w-0 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                          value={contact.email}
                          onChange={(event) => updateContact(contact.key, "email", event.target.value)}
                          aria-label={`Email контакта ${index + 1}`}
                        />
                      </label>
                      <label className="flex min-w-0 items-center gap-2 self-end pb-2 text-sm text-muted">
                        <input
                          type="checkbox"
                          checked={contact.is_primary}
                          onChange={(event) => updateContact(contact.key, "is_primary", event.target.checked)}
                          aria-label={`Основной контакт ${index + 1}`}
                        />
                        Основной контакт
                      </label>
                    </div>
                    {!contact.id && (
                      <button
                        type="button"
                        onClick={() => removeNewContact(contact.key)}
                        className="mt-2 text-xs font-medium text-muted underline hover:text-ink"
                      >
                        Удалить новый контакт
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {lookupError && <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700" role="status">{lookupError}</p>}
          {preview && (
            <fieldset className="min-w-0 rounded-2xl border border-accent/20 bg-accent-soft/30 p-5">
              <legend className="px-1 text-[11px] font-semibold uppercase tracking-wide text-accent-ink">Предпросмотр реестра</legend>
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 text-xs text-muted">
                <span>Источник: {sourceMeta(preview.data.source).label}</span>
                <span>Получено: {formatAuditDate(preview.data.fetched_at)}</span>
              </div>
              <p className="mt-2 text-xs text-muted">Отметьте поля, которые разрешаете сохранить из этого предпросмотра.</p>
              <div className="mt-3 min-w-0 space-y-2">
                {REGISTRY_FIELDS.map((field) => {
                  const changed = currentValue(draft, field) !== preview.values[field];
                  return (
                    <label key={field} className="flex min-w-0 flex-wrap items-start gap-2 rounded-xl bg-surface px-3 py-2 text-sm text-ink">
                      <input
                        type="checkbox"
                        checked={selectedFields.has(field)}
                        onChange={() => toggleRegistryField(field)}
                        aria-label={`Выбрать ${REGISTRY_LABELS[field]}`}
                      />
                      <span className="min-w-0 flex-1 break-words">
                        <span className="font-medium">{REGISTRY_LABELS[field]}:</span> {preview.values[field] || "—"}
                      </span>
                      <span className={`w-full pl-6 text-xs ${changed ? "text-amber-700" : "text-muted"} sm:w-auto sm:pl-0`}>
                        {changed ? "Изменится" : "Без изменений"}
                      </span>
                    </label>
                  );
                })}
              </div>
              <p className="mt-3 text-xs text-muted">Выбрано: {selectedFields.size} из {REGISTRY_FIELDS.length}</p>
            </fieldset>
          )}

          {saveError && <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{saveError}</p>}
          {saveNotice && <p className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700" role="status">{saveNotice}</p>}

          <div className="flex min-w-0 flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={cancel}
              disabled={busy}
              className="rounded-xl border border-line px-4 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-50"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
            >
              {busy ? "Сохранение…" : "Сохранить"}
            </button>
          </div>
          </fieldset>
        </form>
      )}
    </section>
  );
}
