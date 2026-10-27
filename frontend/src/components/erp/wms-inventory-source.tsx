"use client";

import { useEffect, useRef, useState } from "react";
import {
  type InventoryConfirmation, type InventoryOrganization, inventoryErrorMessage,
} from "@/lib/wms-inventory";

export interface SourceDraft { source: "" | "wms_physical"; evidence: string; confirmed: boolean }
export const emptySourceDraft = (): SourceDraft => ({ source: "", evidence: "", confirmed: false });
export function sourceReady(draft: SourceDraft) {
  return draft.source === "wms_physical" && draft.evidence.trim().length > 0 && draft.confirmed;
}
export function sourcePayload(draft: SourceDraft): InventoryConfirmation {
  if (!sourceReady(draft)) throw new Error("Выберите источник, укажите основание и подтвердите полноту журнала.");
  return { expected_source: "wms_physical", source_evidence: draft.evidence.trim(), journal_complete: true };
}

export function InventoryOrganizationSelect({ organizations, value, onChange }: {
  organizations: InventoryOrganization[]; value: number | null; onChange: (id: number | null) => void;
}) {
  return <label className="block text-sm">Юрлицо
    <select aria-label="Юрлицо" value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      className="ml-2 rounded-lg border border-line bg-surface px-3 py-2">
      <option value="">Выберите юрлицо</option>
      {organizations.map((org) => <option key={org.id} value={org.id}>{org.name} · {org.unp}</option>)}
    </select>
    {organizations.length === 0 && <span className="ml-2 text-muted">Нет доступных юрлиц</span>}
  </label>;
}

export function InventorySourceFields({ draft, onChange, disabled = false }: {
  draft: SourceDraft; onChange: (draft: SourceDraft) => void; disabled?: boolean;
}) {
  return <fieldset disabled={disabled} className="mt-3 space-y-3 rounded-xl border border-line p-3">
    <legend className="px-1 text-sm font-medium">Источник и основание пересчёта</legend>
    <label className="block text-sm">Источник ожидаемого остатка
      <select aria-label="Источник ожидаемого остатка" value={draft.source}
        onChange={(e) => onChange({ ...draft, source: e.target.value as SourceDraft["source"], confirmed: false })}
        className="ml-2 rounded-lg border border-line bg-surface px-3 py-2">
        <option value="">Выберите источник</option>
        <option value="wms_physical">Физический журнал WMS</option>
      </select>
    </label>
    <p className="text-sm text-muted">Используются физические движения выбранного юрлица и склада. Это не подтверждение сверки с 1С. Без подтверждённой себестоимости денежная оценка неизвестна.</p>
    <label className="block text-sm">Основание проверки полноты
      <textarea aria-label="Основание проверки полноты" maxLength={1000} value={draft.evidence}
        onChange={(e) => onChange({ ...draft, evidence: e.target.value, confirmed: false })}
        className="mt-1 block w-full rounded-lg border border-line bg-surface px-3 py-2" />
    </label>
    <label className="flex items-start gap-2 text-sm">
      <input type="checkbox" checked={draft.confirmed} onChange={(e) => onChange({ ...draft, confirmed: e.target.checked })} />
      Подтверждаю полноту физического журнала выбранного юрлица и всего указанного склада
    </label>
  </fieldset>;
}

export function useInventoryRequestScope() {
  const generation = useRef(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => () => { generation.current += 1; }, []);
  function begin() { const ticket = ++generation.current; setBusy(true); setError(""); return ticket; }
  function current(ticket: number) { return generation.current === ticket; }
  function finish(ticket: number) { if (current(ticket)) setBusy(false); }
  function fail(ticket: number, reason: unknown) { if (current(ticket)) setError(inventoryErrorMessage(reason)); }
  return { busy, error, setError, begin, current, finish, fail };
}
