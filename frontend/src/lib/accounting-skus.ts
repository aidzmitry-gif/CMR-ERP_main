export type AccountingSku = { id: number; code: string; title: string; unit: string };

export async function searchAccountingSkus(org: string, term: string): Promise<AccountingSku[]> {
  const book = Number(org);
  if (!Number.isSafeInteger(book) || book <= 0 || !term.trim()) return [];
  const response = await fetch(`/api/accounting/organizations/${book}/inventory/skus?q=${encodeURIComponent(term.trim())}`,
    { cache: "no-store" });
  if (!response.ok) throw new Error(`Справочник номенклатуры недоступен (${response.status})`);
  const page: unknown = await response.json();
  if (!page || typeof page !== "object" || (page as { organization_id?: unknown }).organization_id !== book
      || !Array.isArray((page as { items?: unknown }).items))
    throw new Error("Справочник номенклатуры ответил для другого юрлица");
  const items = (page as { items: AccountingSku[] }).items;
  if (items.length > 50 || items.some(item => !Number.isSafeInteger(item.id) || item.id <= 0
      || typeof item.code !== "string" || !item.code || typeof item.title !== "string" || !item.title
      || typeof item.unit !== "string" || !item.unit))
    throw new Error("Справочник номенклатуры вернул некорректные записи");
  return items;
}
