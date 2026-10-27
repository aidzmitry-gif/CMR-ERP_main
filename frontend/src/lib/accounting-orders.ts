export type AccountingProductionOrder = {
  order: string;
  order_source: "production";
  order_id: string;
  order_number: string;
  order_product: string;
  order_quantity: string;
  order_created_at: string;
  order_digest: string;
  order_stage_at_ownership: string;
};

const isText = (value: unknown): value is string =>
  typeof value === "string" && value.trim().length > 0 && value.length <= 200;

function parseOrder(value: unknown): AccountingProductionOrder {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Справочник производственных заказов содержит некорректную запись");
  }
  const row = value as Record<string, unknown>;
  if (row.order_source !== "production"
      || typeof row.order_id !== "string" || !/^[1-9]\d{0,9}$/.test(row.order_id)
      || Number(row.order_id) > 2_147_483_647
      || !isText(row.order) || !isText(row.order_number) || row.order !== row.order_number
      || !isText(row.order_product)
      || typeof row.order_quantity !== "string"
      || row.order_quantity.length > 200
      || !/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(row.order_quantity)
      || !Number.isFinite(Number(row.order_quantity)) || Number(row.order_quantity) <= 0
      || Number(row.order_quantity) > 2_147_483_647
      || typeof row.order_created_at !== "string" || row.order_created_at.length > 200
      || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/.test(row.order_created_at)
      || !Number.isFinite(Date.parse(row.order_created_at))
      || typeof row.order_digest !== "string" || !/^[a-f0-9]{64}$/.test(row.order_digest)
      || !isText(row.order_stage_at_ownership)) {
    throw new Error("Справочник производственных заказов вернул неполную или некорректную запись");
  }
  return {
    order: row.order,
    order_source: "production",
    order_id: row.order_id,
    order_number: row.order_number,
    order_product: row.order_product,
    order_quantity: row.order_quantity,
    order_created_at: row.order_created_at,
    order_digest: row.order_digest,
    order_stage_at_ownership: row.order_stage_at_ownership,
  };
}

export async function searchAccountingProductionOrders(
  org: string,
  term: string,
): Promise<AccountingProductionOrder[]> {
  if (!/^[1-9]\d{0,9}$/.test(org) || Number(org) > 2_147_483_647) return [];
  const query = term.trim();
  if (!query || query.length > 100) return [];
  const book = Number(org);
  const response = await fetch(
    `/api/accounting/organizations/${book}/manual-orders?q=${encodeURIComponent(query)}`,
    { cache: "no-store" },
  );
  if (!response.ok) throw new Error(`Справочник производственных заказов недоступен (${response.status})`);
  const page: unknown = await response.json();
  if (!page || typeof page !== "object" || Array.isArray(page)
      || (page as { organization_id?: unknown }).organization_id !== book
      || !Array.isArray((page as { items?: unknown }).items)) {
    throw new Error("Справочник производственных заказов ответил для другой организации");
  }
  const items = (page as { items: unknown[] }).items;
  if (items.length > 50) {
    throw new Error("Справочник производственных заказов вернул слишком много записей");
  }
  return items.map(parseOrder);
}
