import type { AiCatalog, ReferenceQueryInput } from "@/lib/reference-data";

/** Strip empty/undefined optional fields before calling runReferenceQuery. */
export function buildQueryInput(raw: {
  ref: string;
  key: string;
  as_of: string;
  name: string;
  limit: string;
}): ReferenceQueryInput {
  const input: ReferenceQueryInput = { ref: raw.ref };
  if (raw.key.trim()) input.key = raw.key.trim();
  if (raw.as_of.trim()) input.as_of = raw.as_of.trim();
  if (raw.name.trim()) input.name = raw.name.trim();
  const n = parseInt(raw.limit, 10);
  if (!isNaN(n) && n > 0) input.limit = n;
  return input;
}

/** Fallback catalog when backend unavailable (mirrors expected real data shape). */
export const FALLBACK_CATALOG: AiCatalog = {
  tool: {
    name: "reference.query",
    endpoint: "/system/references/query",
    params: ["ref", "key", "as_of", "name", "limit"],
    note: "Структурный SQL-запрос с учётом историчности (SCD2).",
  },
  references: [
    {
      key: "core.counterparties",
      title: "Контрагенты",
      endpoint: "/refs/counterparties",
      owner_schema: "public",
      versioned: false,
      columns: [
        { name: "unp", type: "string", semantic: "counterparty.tax_id" },
        { name: "name", type: "string", semantic: "counterparty.name" },
        { name: "is_active", type: "bool", semantic: "counterparty.active" },
      ],
      description: "Эталонные карточки клиентов и поставщиков (golden record).",
    },
    {
      key: "core.skus",
      title: "Номенклатура",
      endpoint: "/refs/skus",
      owner_schema: "public",
      versioned: false,
      columns: [
        { name: "code", type: "string", semantic: "sku.code" },
        { name: "name", type: "string", semantic: "sku.name" },
        { name: "unit", type: "string", semantic: "sku.unit" },
      ],
      description: "Товары и SKU с артикулами и единицами учёта.",
    },
    {
      key: "core.units",
      title: "Единицы измерения",
      endpoint: "/refs/units",
      owner_schema: "public",
      versioned: false,
      columns: [
        { name: "code", type: "string", semantic: "unit.code" },
        { name: "title", type: "string", semantic: "unit.label" },
      ],
      description: "Базовые и производные единицы, коэффициенты пересчёта.",
    },
    {
      key: "core.currency_rates",
      title: "Валюты и курсы",
      endpoint: "/refs/currencies",
      owner_schema: "public",
      versioned: true,
      columns: [
        { name: "currency_code", type: "string", semantic: "currency.code" },
        { name: "rate", type: "number", semantic: "currency.rate" },
        { name: "start_date", type: "date", semantic: "scd2.start_date" },
      ],
      description: "Версионные курсы НБ РБ — значение на любую дату.",
    },
    {
      key: "core.vat_rates",
      title: "Ставки НДС",
      endpoint: "/refs/vat-rates",
      owner_schema: "public",
      versioned: true,
      columns: [
        { name: "code", type: "string", semantic: "vat.code" },
        { name: "rate", type: "number", semantic: "vat.rate" },
        { name: "start_date", type: "date", semantic: "scd2.start_date" },
      ],
      description: "Интервалы действия ставок — ставка на дату документа.",
    },
    {
      key: "core.nomenclature_groups",
      title: "Категории",
      endpoint: "/refs/categories",
      owner_schema: "public",
      versioned: false,
      columns: [
        { name: "code", type: "string", semantic: "category.code" },
        { name: "name", type: "string", semantic: "category.name" },
        { name: "parent_id", type: "number", semantic: "category.parent" },
      ],
      description: "Иерархический классификатор номенклатуры (дерево).",
    },
  ],
};
