export type AccountingSettlementDocument = {
  source: "procurement" | "sales";
  id: number;
  number: string;
  version: number;
  reference: string;
};

export async function searchAccountingSettlementDocuments(org: string, counterpartyId: string, term: string): Promise<AccountingSettlementDocument[]> {
  const book = Number(org), counterparty = Number(counterpartyId);
  if (!Number.isSafeInteger(book) || book <= 0 || !Number.isSafeInteger(counterparty)
      || counterparty <= 0 || !term.trim()) return [];
  const response = await fetch(`/api/accounting/organizations/${book}/settlement-documents?counterparty_id=${counterparty}&q=${encodeURIComponent(term.trim())}`,
    { cache: "no-store" });
  if (!response.ok) throw new Error(`Реестр документов расчётов недоступен (${response.status})`);
  const page: unknown = await response.json();
  if (!page || typeof page !== "object"
      || (page as { organization_id?: unknown }).organization_id !== book
      || (page as { counterparty_id?: unknown }).counterparty_id !== counterparty
      || !Array.isArray((page as { items?: unknown }).items))
    throw new Error("Реестр документов расчётов ответил для другого юрлица или контрагента");
  const items = (page as { items: AccountingSettlementDocument[] }).items;
  if (items.length > 50 || items.some(item => !["procurement", "sales"].includes(item.source)
      || !Number.isSafeInteger(item.id) || item.id <= 0
      || !Number.isSafeInteger(item.version) || item.version <= 0
      || typeof item.number !== "string" || !item.number
      || item.reference !== (item.source === "procurement"
        ? `procurement:receipt:${item.id}:${item.version}` : `sales:document:${item.id}`)))
    throw new Error("Реестр документов расчётов вернул некорректные записи");
  return items;
}
