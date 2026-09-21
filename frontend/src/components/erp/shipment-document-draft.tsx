"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";

type Draft = {
  status: "draft_required";
  document_kind: "tn" | "ttn" | null;
  document_label: string | null;
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
  statutory_certified: false;
  can_issue: false;
};

const policyStatus = (draft: Draft) => {
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
};

export function ShipmentDocumentDraft({ org, sourceKey }: { org: string; sourceKey: string }) {
  const [kind, setKind] = useState<"tn" | "ttn">("ttn");
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  /* eslint-disable react-hooks/set-state-in-effect -- request state is reset when the external source query changes. */
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true); setError("");
    void fetch(`/api/accounting/organizations/${org}/shipments/${sourceKey}/tn-ttn-draft?kind=${kind}`, { cache: "no-store" })
      .then(async (response) => { const value = await response.json(); if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Черновик ТН/ТТН недоступен."); return value as Draft; })
      .then((value) => { if (active) setDraft(value); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Черновик ТН/ТТН недоступен."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [kind, open, org, sourceKey]);
  /* eslint-enable react-hooks/set-state-in-effect */
  return <div className="mt-1 space-y-2">
    <Button variant="secondary" onClick={() => setOpen((value) => !value)}>{open ? "Скрыть подготовку ТН/ТТН" : "Подготовить ТН/ТТН"}</Button>
    {open && <div className="rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-950">
      <label className="flex items-center gap-2">Вид<Select aria-label="Вид отгрузочного документа" value={kind} onChange={(event) => setKind(event.target.value as "tn" | "ttn")}><option value="tn">ТН</option><option value="ttn">ТТН</option></Select></label>
      {loading && <p role="status" className="mt-2">Подготавливаем поля из проверенного акта…</p>}
      {error && <p role="alert" className="mt-2">{error}</p>}
      {draft && <div className="mt-2 space-y-2"><p><b>Черновик {draft.document_label}</b> · операция {draft.prefilled.operation_date} · количество {draft.prefilled.total_quantity}</p><p className="font-semibold">Документ не выпущен: внутренний акт WMS не является ТН/ТТН.</p><p>Учётная политика: {policyStatus(draft)}</p><ul className="list-disc pl-5">{draft.blockers.map((item) => <li key={item}>{item}</li>)}</ul><p>Нужно заполнить: {draft.required_fields.join(", ")}.</p><ul className="list-disc pl-5">{draft.prefilled.items.map((item) => <li key={item.line_no}>строка {item.line_no}: {item.sku_code} · {item.quantity}</li>)}</ul></div>}
    </div>}
  </div>;
}
