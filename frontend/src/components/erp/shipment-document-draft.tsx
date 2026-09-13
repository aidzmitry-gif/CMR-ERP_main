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
  statutory_certified: false;
  can_issue: false;
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
      {draft && <div className="mt-2 space-y-2"><p><b>Черновик {draft.document_label}</b> · операция {draft.prefilled.operation_date} · количество {draft.prefilled.total_quantity}</p><p className="font-semibold">Документ не выпущен: внутренний акт WMS не является ТН/ТТН.</p><ul className="list-disc pl-5">{draft.blockers.map((item) => <li key={item}>{item}</li>)}</ul><p>Нужно заполнить: {draft.required_fields.join(", ")}.</p><ul className="list-disc pl-5">{draft.prefilled.items.map((item) => <li key={item.line_no}>строка {item.line_no}: {item.sku_code} · {item.quantity}</li>)}</ul></div>}
    </div>}
  </div>;
}
