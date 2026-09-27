"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { ShipmentDocumentDraft } from "@/components/erp/shipment-document-draft";
import {
  fetchShipmentPreparationRegister,
  type ShipmentDocumentReference,
  type ShipmentDraftRegistryItem,
} from "@/lib/document-register-api";

type Props = {
  organizationId: number;
  items: ShipmentDocumentReference[];
  title: string;
  description: string;
};

export function ShipmentDocumentsRegister({ organizationId, items, title, description }: Props) {
  const sourceKeys = useMemo(() => items.map((item) => item.source_key), [items]);
  const [registryState, setRegistryState] = useState<{ organizationId: number; items: ShipmentDraftRegistryItem[] } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  /* eslint-disable react-hooks/set-state-in-effect -- request state follows the current authorized source list. */
  useEffect(() => {
    let active = true;
    setError("");
    if (sourceKeys.length === 0) {
      setRegistryState({ organizationId, items: [] });
      setLoading(false);
      return () => { active = false; };
    }
    setLoading(true);
    void fetchShipmentPreparationRegister(String(organizationId), sourceKeys)
      .then((result) => { if (active) setRegistryState({ organizationId, items: result.items }); })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : "Не удалось проверить черновики ТН/ТТН."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [organizationId, sourceKeys, attempt]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const registry = registryState?.organizationId === organizationId ? registryState.items : null;
  const bySource = new Map(registry?.map((item) => [item.source_key.toLowerCase(), item]) ?? []);
  return <section aria-label={title} className="space-y-2 rounded-lg border border-line p-3 text-sm">
    <h3 className="font-semibold">{title}</h3>
    <p className="text-xs text-muted">{description}</p>
    {loading && <p role="status">Проверяем список черновиков ТН/ТТН…</p>}
    {error && <div><p role="alert" className="text-red-700">{error} {registry
      ? "Показан предыдущий список; при открытии номера сервер заново сверит редакцию."
      : "Состав черновиков неизвестен."}</p>
      <Button variant="secondary" onClick={() => setAttempt((current) => current + 1)}>Повторить загрузку черновиков</Button></div>}
    {!error && <Button variant="secondary" disabled={loading}
      onClick={() => setAttempt((current) => current + 1)}>Обновить список черновиков</Button>}
    <ul className="space-y-2">
      {items.map((row) => {
        const drafts = bySource.get(row.source_key.toLowerCase());
        return <li key={row.act_id} className="border-b border-line pb-2 last:border-0">
          <a className="text-accent underline" href={row.document_url} target="_blank" rel="noreferrer">Акт WMS № {row.act_id}</a>
          <span> · счёт ID {row.document_id} · дата {row.operation_date} · строк {row.line_count} · {row.actor}</span>
          {drafts?.status === "unavailable" && <p role="alert" className="text-amber-800">Черновики для этого акта не показаны: источник или покупатель не удалось подтвердить.</p>}
          {drafts?.status === "verified" && <ShipmentDocumentDraft
            org={String(organizationId)} sourceKey={row.source_key} preparationDocuments={drafts.preparation_documents}
          />}
        </li>;
      })}
    </ul>
  </section>;
}
