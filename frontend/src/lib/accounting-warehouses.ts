export type AccountingWarehouse = { id: number; name: string; title: string };

export async function searchAccountingWarehouses(org: string, term: string): Promise<AccountingWarehouse[]> {
  const book = Number(org);
  if (!Number.isSafeInteger(book) || book <= 0 || !term.trim()) return [];
  const response = await fetch(`/api/accounting/organizations/${book}/inventory/warehouses?q=${encodeURIComponent(term.trim())}`,
    { cache: "no-store" });
  if (!response.ok) throw new Error(`Справочник складов недоступен (${response.status})`);
  const page: unknown = await response.json();
  if (!page || typeof page !== "object" || (page as { organization_id?: unknown }).organization_id !== book
      || !Array.isArray((page as { items?: unknown }).items))
    throw new Error("Справочник складов ответил для другого юрлица");
  const items = (page as { items: AccountingWarehouse[] }).items;
  if (items.length > 50 || items.some(item => !Number.isSafeInteger(item.id) || item.id <= 0
      || typeof item.name !== "string" || !item.name || typeof item.title !== "string" || !item.title))
    throw new Error("Справочник складов вернул некорректные записи");
  return items;
}
