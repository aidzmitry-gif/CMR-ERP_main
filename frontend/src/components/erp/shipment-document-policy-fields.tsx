"use client";

import { useEffect, useState } from "react";

import { Input, Select } from "@/components/ui/input";

export type ShipmentDocumentScenario = {
  kind: "tn" | "ttn";
  exchange_mode: "paper" | "electronic";
  form_version: string;
  numbering_rule: string;
  signing_rule: string;
  exchange_rule: string;
  evidence: string;
};

export type ShipmentDocumentPolicySelection = {
  scope: string;
  enabled: boolean;
  value: { scenarios: ShipmentDocumentScenario[] } | null;
};

type ShipmentDocumentScenarioDraft = Omit<ShipmentDocumentScenario, "exchange_mode"> & {
  exchange_mode: "" | ShipmentDocumentScenario["exchange_mode"];
};

const blank = (kind: "tn" | "ttn"): ShipmentDocumentScenarioDraft => ({
  kind, exchange_mode: "", form_version: "", numbering_rule: "", signing_rule: "", exchange_rule: "", evidence: "",
});

const complete = (value: ShipmentDocumentScenarioDraft): value is ShipmentDocumentScenario =>
  (value.exchange_mode === "paper" || value.exchange_mode === "electronic") && [
    value.form_version, value.numbering_rule, value.signing_rule, value.exchange_rule, value.evidence,
  ].every((field) => field.trim().length > 0);

type ScenarioFieldsProps = {
  title: string;
  enabled: boolean;
  value: ShipmentDocumentScenarioDraft;
  onEnabledChange: (value: boolean) => void;
  onChange: (value: ShipmentDocumentScenarioDraft) => void;
};

function ScenarioFields({ title, enabled, value, onEnabledChange, onChange }: ScenarioFieldsProps) {
  return <fieldset className="space-y-2 rounded border border-line p-3">
    <legend className="px-1 text-sm font-medium"><label><input type="checkbox" checked={enabled} onChange={(event) => onEnabledChange(event.target.checked)} /> Настроить {title}</label></legend>
    {enabled && <div className="grid gap-3 md:grid-cols-2">
      <label className="text-sm">Способ оформления {title}<Select aria-label={`${title} — способ оформления`} value={value.exchange_mode} onChange={(event) => onChange({ ...value, exchange_mode: event.target.value as ShipmentDocumentScenarioDraft["exchange_mode"] })}><option value="">Выберите способ оформления</option><option value="paper">Бумажный</option><option value="electronic">Электронный</option></Select></label>
      <Input aria-label={`${title} — версия формы`} placeholder="Форма / версия, утверждённая бухгалтером" value={value.form_version} onChange={(event) => onChange({ ...value, form_version: event.target.value })} />
      <Input aria-label={`${title} — правило нумерации`} placeholder="Правило нумерации" value={value.numbering_rule} onChange={(event) => onChange({ ...value, numbering_rule: event.target.value })} />
      <Input aria-label={`${title} — правило подписания`} placeholder="Подписанты и правило подписания" value={value.signing_rule} onChange={(event) => onChange({ ...value, signing_rule: event.target.value })} />
      <Input aria-label={`${title} — маршрут обмена`} placeholder="Маршрут обмена / внешний оператор" value={value.exchange_rule} onChange={(event) => onChange({ ...value, exchange_rule: event.target.value })} />
      <Input aria-label={`${title} — доказательство`} placeholder="Приказ, договор или другая проверяемая ссылка" value={value.evidence} onChange={(event) => onChange({ ...value, evidence: event.target.value })} />
    </div>}
  </fieldset>;
}

export function ShipmentDocumentPolicyFields({ org, effectiveDate, onChange }: { org: string; effectiveDate: string; onChange: (value: ShipmentDocumentPolicySelection) => void }) {
  return <Fields key={`${org}:${effectiveDate}`} org={org} effectiveDate={effectiveDate} onChange={onChange} />;
}

function Fields({ org, effectiveDate, onChange }: { org: string; effectiveDate: string; onChange: (value: ShipmentDocumentPolicySelection) => void }) {
  const scope = `${org}:${effectiveDate}`;
  const [enabled, setEnabled] = useState(false);
  const [tnEnabled, setTnEnabled] = useState(false);
  const [ttnEnabled, setTtnEnabled] = useState(false);
  const [tn, setTn] = useState(() => blank("tn"));
  const [ttn, setTtn] = useState(() => blank("ttn"));

  useEffect(() => {
    const selected = [tnEnabled ? tn : null, ttnEnabled ? ttn : null].filter((value): value is ShipmentDocumentScenarioDraft => value !== null);
    const scenarios = selected.filter(complete);
    onChange({ scope, enabled, value: enabled && selected.length > 0 && scenarios.length === selected.length ? { scenarios } : null });
  }, [enabled, onChange, scope, tn, tnEnabled, ttn, ttnEnabled]);

  return <fieldset className="min-w-0 space-y-2 rounded-lg border border-line p-3">
    <legend>ТН/ТТН и электронные накладные</legend>
    <label className="block text-sm"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /> Настроить применимые сценарии ТН/ТТН</label>
    {enabled && <><p className="text-sm text-muted">Заполните только применимые сценарии действующей версии политики. Внутренний акт WMS не выбирает вид, форму, номер, подписантов или оператора автоматически.</p>
      <ScenarioFields title="ТН" enabled={tnEnabled} value={tn} onEnabledChange={setTnEnabled} onChange={setTn} />
      <ScenarioFields title="ТТН" enabled={ttnEnabled} value={ttn} onEnabledChange={setTtnEnabled} onChange={setTtn} />
      <p className="text-sm text-muted">Настройка сохраняет только policy-by-org-and-period для подготовки черновика. Она не выпускает ТН/ТТН, не подписывает ЭЦП и не отправляет документ внешнему оператору.</p>
    </>}
  </fieldset>;
}
