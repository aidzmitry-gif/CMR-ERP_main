export type AccountingBuyer = { id: number; name: string; unp: string; revision: number };

export async function searchAccountingBuyers(org: string, term: string): Promise<AccountingBuyer[]> {
  const book = Number(org);
  if (!Number.isSafeInteger(book) || book <= 0 || !term.trim()) return [];
  const response = await fetch(`/api/accounting/organizations/${book}/sales/buyers?q=${encodeURIComponent(term.trim())}`,
    { cache: "no-store" });
  if (!response.ok) throw new Error(`Справочник покупателей недоступен (${response.status})`);
  const page: unknown = await response.json();
  if (!page || typeof page !== "object" || (page as { organization_id?: unknown }).organization_id !== book
      || !Array.isArray((page as { items?: unknown }).items))
    throw new Error("Справочник покупателей ответил для другого юрлица");
  const items = (page as { items: AccountingBuyer[] }).items;
  if (items.length > 50 || items.some(item => !Number.isSafeInteger(item.id) || item.id <= 0
      || !Number.isSafeInteger(item.revision) || item.revision <= 0
      || typeof item.name !== "string" || typeof item.unp !== "string"))
    throw new Error("Справочник покупателей вернул некорректные записи");
  return items;
}
