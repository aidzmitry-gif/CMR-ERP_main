"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";

type ItemDraft = { line_no: number; unit: string; unit_price: string; vat_basis: string };
type Fields = {
  sender_legal_entity: string;
  recipient_legal_entity: string;
  contract_reference: string;
  document_number: string;
  document_date: string;
  carrier: string;
  vehicle_registration: string;
  driver: string;
  route: string;
  loading_point: string;
  unloading_point: string;
  items: ItemDraft[];
};
type HistoryChange = { field: string; before: string | null; after: string | null };
type HistoryVersion = {
  id: number;
  revision: number;
  actor: string;
  created_at: string | null;
  fields: Partial<Fields>;
  changes: HistoryChange[];
};
type Draft = {
  status: "draft_required";
  document_kind: "tn" | "ttn" | null;
  document_label: string | null;
  source: { source_key: string; digest: string };
  prefilled: { operation_date: string; total_quantity: string; items: Array<{ line_no: number; sku_code: string; quantity: string }> };
  required_fields: string[];
  blockers: string[];
  shipment_document_policy: {
    status: "missing_accounting_policy" | "document_kind_not_selected" | "missing_shipment_document_policy" | "document_kind_not_configured" | "invalid_shipment_document_policy" | "normative_basis_unverified" | "review_ready";
    policy_id: number | null;
    effective_from: string | null;
    normative_verified: boolean | null;
    scenario: { kind: "tn" | "ttn"; exchange_mode: "paper" | "electronic"; form_version: string; numbering_rule: string; signing_rule: string; exchange_rule: string; evidence: string } | null;
  };
  saved_revision: number;
  saved_fields: Partial<Fields>;
  saved_by: string | null;
  saved_at: string | null;
  history: HistoryVersion[];
  source_history_current: boolean;
  statutory_certified: false;
  can_issue: false;
};

const textInputs: Array<[keyof Omit<Fields, "items">, string]> = [
  ["sender_legal_entity", "Отправитель (черновые реквизиты)"],
  ["recipient_legal_entity", "Получатель (черновые реквизиты)"],
  ["contract_reference", "Договор / основание"],
  ["document_number", "Черновой номер (не официальный)"],
  ["document_date", "Дата документа"],
];
const ttnInputs: Array<[keyof Omit<Fields, "items">, string]> = [
  ["carrier", "Перевозчик"],
  ["vehicle_registration", "Регистрационный номер автомобиля"],
  ["driver", "Водитель"],
  ["route", "Маршрут"],
  ["loading_point", "Пункт погрузки"],
  ["unloading_point", "Пункт разгрузки"],
];
const itemLabels: Record<string, string> = { unit: "Единица измерения", unit_price: "Цена (черновое значение)", vat_basis: "Основание НДС (черновое значение)" };

function emptyFields(draft: Draft | null): Fields {
  const saved = draft?.saved_fields ?? {};
  const itemValues = saved.items ?? draft?.prefilled.items.map((item) => ({ line_no: item.line_no, unit: "", unit_price: "", vat_basis: "" })) ?? [];
  return {
    sender_legal_entity: saved.sender_legal_entity ?? "",
    recipient_legal_entity: saved.recipient_legal_entity ?? "",
    contract_reference: saved.contract_reference ?? "",
    document_number: saved.document_number ?? "",
    document_date: saved.document_date ?? "",
    carrier: saved.carrier ?? "",
    vehicle_registration: saved.vehicle_registration ?? "",
    driver: saved.driver ?? "",
    route: saved.route ?? "",
    loading_point: saved.loading_point ?? "",
    unloading_point: saved.unloading_point ?? "",
    items: itemValues.map((item) => ({ line_no: item.line_no, unit: item.unit ?? "", unit_price: item.unit_price ?? "", vat_basis: item.vat_basis ?? "" })),
  };
}

function rebaseFields(base: Fields, local: Fields, latest: Fields): Fields {
  const merged = { ...latest };
  for (const [field] of [...textInputs, ...ttnInputs]) {
    if (local[field] !== base[field]) merged[field] = local[field];
  }
  const latestItems = new Map(latest.items.map((item) => [item.line_no, { ...item }]));
  const baseItems = new Map(base.items.map((item) => [item.line_no, item]));
  for (const localItem of local.items) {
    const current = latestItems.get(localItem.line_no);
    const original = baseItems.get(localItem.line_no);
    if (!current || !original) continue;
    for (const field of ["unit", "unit_price", "vat_basis"] as const) {
      if (localItem[field] !== original[field]) current[field] = localItem[field];
    }
  }
  merged.items = [...latestItems.values()];
  return merged;
}

function policyStatus(draft: Draft) {
  const policy = draft.shipment_document_policy;
  if (policy.status === "review_ready") return policy.scenario
    ? `Версия политики № ${policy.policy_id} от ${policy.effective_from}: ${policy.scenario.kind === "tn" ? "ТН" : "ТТН"}, ${policy.scenario.exchange_mode === "electronic" ? "электронный" : "бумажный"} сценарий заполнен. Выпуск всё равно недоступен.`
    : "Сценарий ТН/ТТН в политике не передан сервером.";
  const labels: Record<Exclude<typeof policy.status, "review_ready">, string> = {
    missing_accounting_policy: "На дату операции нет применимой учётной политики.",
    document_kind_not_selected: "Не выбран вид документа.",
    missing_shipment_document_policy: "В версии учётной политики нет сценария ТН/ТТН.",
    document_kind_not_configured: "Для выбранного вида нет сценария ТН/ТТН.",
    invalid_shipment_document_policy: "Сценарий ТН/ТТН в политике неполный.",
    normative_basis_unverified: "Нормативная база версии политики не подтверждена бухгалтером.",
  };
  return labels[policy.status];
}

function readableField(path: string) {
  if (path.startsWith("items.line_")) {
    const [, line, field] = path.match(/^items\.line_(\d+)\.(.+)$/) ?? [];
    return `Строка ${line}: ${itemLabels[field] ?? field}`;
  }
  return new Map<string, string>([...textInputs, ...ttnInputs]).get(path) ?? path;
}

export function ShipmentDocumentDraft({ org, sourceKey }: { org: string; sourceKey: string }) {
  const [kind, setKind] = useState<"tn" | "ttn">("ttn");
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [fields, setFields] = useState<Fields>(() => emptyFields(null));
  const [baseFields, setBaseFields] = useState<Fields>(() => emptyFields(null));
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [pendingRequestKey, setPendingRequestKey] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  /* eslint-disable react-hooks/set-state-in-effect -- request state follows the external source query. */
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError("");
    setNotice("");
    setDraft(null);
    void fetch(`/api/accounting/organizations/${org}/shipments/${sourceKey}/tn-ttn-draft?kind=${kind}`, { cache: "no-store" })
      .then(async (response) => {
        const value = await response.json();
        if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Черновик ТН/ТТН недоступен.");
        return value as Draft;
      })
      .then((value) => {
        if (!active) return;
        setDraft(value);
        setFields(emptyFields(value));
        setBaseFields(emptyFields(value));
        setDirty(false);
        setPendingRequestKey(null);
      })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Черновик ТН/ТТН недоступен."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [kind, open, org, sourceKey]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function changeText(field: keyof Omit<Fields, "items">, value: string) {
    setFields((current) => ({ ...current, [field]: value }));
    setDirty(true); setPendingRequestKey(null); setError(""); setNotice("");
  }

  function changeItem(line: number, field: keyof ItemDraft, value: string) {
    setFields((current) => ({ ...current, items: current.items.map((item) => item.line_no === line ? { ...item, [field]: value } : item) }));
    setDirty(true); setPendingRequestKey(null); setError(""); setNotice("");
  }

  function selectKind(next: "tn" | "ttn") {
    if (next === kind) return;
    if (dirty && !window.confirm("Есть несохранённые изменения. Переключить вид документа и потерять их?")) return;
    setDirty(false); setPendingRequestKey(null); setKind(next);
  }

  function closeEditor() {
    if (dirty && !window.confirm("Есть несохранённые изменения. Закрыть без сохранения?")) return;
    setOpen(false);
  }

  async function saveDraft(closeAfterSave: boolean) {
    if (!draft || !draft.source_history_current || saving) return;
    setSaving(true); setError(""); setNotice("");
    const requestKey = pendingRequestKey ?? crypto.randomUUID();
    setPendingRequestKey(requestKey);
    const payloadFields: Record<string, unknown> = {
      sender_legal_entity: fields.sender_legal_entity,
      recipient_legal_entity: fields.recipient_legal_entity,
      contract_reference: fields.contract_reference,
      document_number: fields.document_number,
      document_date: fields.document_date,
      items: fields.items,
    };
    if (kind === "ttn") for (const [field] of ttnInputs) payloadFields[field] = fields[field];
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/shipments/${sourceKey}/tn-ttn-draft`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, request_key: requestKey, expected_revision: draft.saved_revision, source_digest: draft.source.digest, fields: payloadFields }),
      });
      const value = await response.json();
      if (!response.ok) {
        const message = typeof value.detail === "string" ? value.detail : "Не удалось подтвердить сохранение черновика.";
        if (response.status === 409) {
          const refreshedResponse = await fetch(`/api/accounting/organizations/${org}/shipments/${sourceKey}/tn-ttn-draft?kind=${kind}`, { cache: "no-store" });
          const refreshedValue = await refreshedResponse.json();
          if (!refreshedResponse.ok) throw new Error(message);
          const refreshed = refreshedValue as Draft;
          if (refreshed.saved_revision > draft.saved_revision && refreshed.source_history_current && refreshed.source.digest === draft.source.digest) {
            const latestFields = emptyFields(refreshed);
            setDraft(refreshed);
            setBaseFields(latestFields);
            setFields(rebaseFields(baseFields, fields, latestFields));
            setPendingRequestKey(null);
            setError("Появилась параллельная редакция. История обновлена; ваша правка объединена с ней и оставлена на экране. Проверьте значения перед сохранением.");
            return;
          }
        }
        throw new Error(message);
      }
      if (value.saved_revision !== draft.saved_revision + 1 || value.saved_by === null || !value.saved_at) {
        throw new Error("Сервер не подтвердил новую редакцию черновика. Ввод сохранён на экране; обновите историю перед повтором.");
      }
      setDraft(value as Draft);
      setFields(emptyFields(value as Draft));
      setBaseFields(emptyFields(value as Draft));
      setDirty(false); setPendingRequestKey(null);
      setNotice(`Сохранена редакция ${value.saved_revision} · ${value.saved_by} · ${value.saved_at}`);
      if (closeAfterSave) setOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось подтвердить сохранение черновика.");
    } finally {
      setSaving(false);
    }
  }

  return <div className="mt-1 space-y-2">
    <Button variant="secondary" onClick={() => open ? closeEditor() : setOpen(true)}>{open ? "Закрыть подготовку ТН/ТТН" : "Подготовить ТН/ТТН"}</Button>
    {open && <div className="rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">
      <label className="flex items-center gap-2">Вид<Select aria-label="Вид отгрузочного документа" value={kind} onChange={(event) => selectKind(event.target.value as "tn" | "ttn")}><option value="tn">ТН</option><option value="ttn">ТТН</option></Select></label>
      {loading && <p role="status" className="mt-2">Подготавливаем поля из проверенного акта…</p>}
      {error && <p role="alert" className="mt-2">{error}</p>}
      {notice && <p role="status" className="mt-2">{notice}</p>}
      {draft && <div className="mt-3 space-y-3">
        <div><p><b>Черновик {draft.document_label}</b> · редакция {draft.saved_revision} · операция {draft.prefilled.operation_date} · количество {draft.prefilled.total_quantity}</p>
          <p className="font-semibold">Документ не выпущен: акт WMS не является ТН/ТТН.</p>
          <p>Учётная политика: {policyStatus(draft)}</p>
          <p>Реквизиты и номер сохраняются только как черновые значения. Для выпуска потребуется подтвердить их по справочникам и применимому сценарию.</p>
          <ul className="list-disc pl-5">{draft.blockers.map((item) => <li key={item}>{item}</li>)}</ul>
          <p>Обязательные поля для проверки: {draft.required_fields.join(", ")}.</p>
        </div>
        {!draft.source_history_current && <p role="alert" className="font-semibold">Источник сохранённой истории не совпадает с текущим актом. Сохранение заблокировано.</p>}
        <fieldset disabled={loading || saving || !draft.source_history_current} className="space-y-3">
          <legend className="font-semibold">Реквизиты черновика</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {textInputs.map(([field, label]) => <label key={field} className="grid gap-1">{label}<input aria-label={label} type={field === "document_date" ? "date" : "text"} value={fields[field]} onChange={(event) => changeText(field, event.target.value)} className="rounded border border-amber-500 bg-white px-2 py-1 text-slate-900" /></label>)}
            {kind === "ttn" && ttnInputs.map(([field, label]) => <label key={field} className="grid gap-1">{label}<input aria-label={label} type="text" value={fields[field]} onChange={(event) => changeText(field, event.target.value)} className="rounded border border-amber-500 bg-white px-2 py-1 text-slate-900" /></label>)}
          </div>
          <div className="space-y-2"><h4 className="font-semibold">Строки проверенного акта · поля цены и НДС не рассчитываются</h4>
            {draft.prefilled.items.map((sourceItem) => {
              const item = fields.items.find((row) => row.line_no === sourceItem.line_no);
              if (!item) return null;
              return <div key={sourceItem.line_no} className="rounded border border-amber-200 bg-white p-2 text-slate-900">
                <p>Строка {sourceItem.line_no}: {sourceItem.sku_code} · количество {sourceItem.quantity}</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  {(["unit", "unit_price", "vat_basis"] as const).map((field) => <label key={field} className="grid gap-1">{itemLabels[field]}<input aria-label={`Строка ${sourceItem.line_no}: ${itemLabels[field]}`} value={item[field]} onChange={(event) => changeItem(sourceItem.line_no, field, event.target.value)} className="rounded border border-amber-500 px-2 py-1" /></label>)}
                </div>
              </div>;
            })}
          </div>
        </fieldset>
        <div className="flex flex-wrap gap-2">
          <Button disabled={saving || loading || !draft.source_history_current} onClick={() => void saveDraft(false)}>{saving ? "Сохраняем…" : "Сохранить редакцию"}</Button>
          <Button variant="secondary" disabled={saving || loading || !draft.source_history_current} onClick={() => void saveDraft(true)}>{saving ? "Сохраняем…" : "Сохранить и закрыть"}</Button>
          <Button variant="secondary" disabled={saving} onClick={closeEditor}>Закрыть</Button>
        </div>
        <section className="border-t border-amber-300 pt-2">
          <button type="button" className="font-semibold underline" aria-expanded={showHistory} onClick={() => setShowHistory((value) => !value)}>История изменений ({draft.history.length})</button>
          {showHistory && <ol className="mt-2 space-y-2">{draft.history.map((version) => <li key={version.id} className="rounded border border-amber-200 bg-white p-2 text-slate-900">
            <p><b>Редакция {version.revision}</b> · {version.actor} · {version.created_at ?? "время недоступно"}</p>
            {version.changes.length === 0 ? <p>Первая сохранённая редакция; заполненные поля доступны при раскрытии.</p> : <ul className="mt-1 list-disc pl-5">{version.changes.map((change) => <li key={`${version.id}-${change.field}`}><b>{readableField(change.field)}:</b> {change.before ?? "—"} → {change.after ?? "—"}</li>)}</ul>}
          </li>)}</ol>}
        </section>
      </div>}
    </div>}
  </div>;
}
