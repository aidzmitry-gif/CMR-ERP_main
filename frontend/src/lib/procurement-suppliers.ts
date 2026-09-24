// Домен «Справочник поставщиков» поверх backend-API `/procurement/suppliers`.
// Supplier — профиль закупок; новый профиль явно связывается с MDM-контрагентом по ID.
// Исторический профиль может оставаться без ID до ручной сверки.

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export interface Supplier {
  id: number;
  counterparty_id?: number | null;
  name: string;
  unp: string;
  country: string;
  flag: string;
  contact_person: string;
  phone: string;
  email: string;
  payment_terms: string;
  lead_time_days: number | null;
  incoterms: string;
  status: string; // active | blocked
  notes: string;
}

export type SupplierInput = Omit<Supplier, "id">;

export interface SupplierCounterparty { id: number; name: string; unp: string }

export async function searchSupplierCounterparties(term: string): Promise<SupplierCounterparty[]> {
  if (term.trim().length < 2) return [];
  const response = await fetch(`/api/procurement/supplier-counterparties?q=${encodeURIComponent(term.trim())}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Справочник контрагентов недоступен");
  const value: unknown = await response.json();
  if (!value || typeof value !== "object" || !Array.isArray((value as { items?: unknown }).items)) throw new Error("Неверный ответ справочника");
  const items = (value as { items: unknown[] }).items;
  if (!items.every(item => !!item && typeof item === "object" && Number.isSafeInteger((item as SupplierCounterparty).id)
      && (item as SupplierCounterparty).id > 0 && typeof (item as SupplierCounterparty).name === "string"
      && typeof (item as SupplierCounterparty).unp === "string")) throw new Error("Неверный ответ справочника");
  return items as SupplierCounterparty[];
}

const STATUS_LABEL: Record<string, string> = { active: "Активен", blocked: "Заблокирован" };

/** Человекочитаемый статус поставщика (неизвестный — как есть). */
export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** Фильтр по подстроке в имени/УНП/стране (регистронезависимо). */
export function filterSuppliers(rows: Supplier[], q: string): Supplier[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter(
    (s) =>
      s.name.toLowerCase().includes(needle) ||
      s.unp.toLowerCase().includes(needle) ||
      s.country.toLowerCase().includes(needle),
  );
}

/** Пустой профиль для формы создания. */
export function emptySupplier(): SupplierInput {
  return {
    counterparty_id: null,
    name: "",
    unp: "",
    country: "",
    flag: "",
    contact_person: "",
    phone: "",
    email: "",
    payment_terms: "",
    lead_time_days: null,
    incoterms: "",
    status: "active",
    notes: "",
  };
}

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

/** Поставщики для SSR (server component); при недоступности бэка — пусто. */
export async function fetchSuppliersServer(roles?: string): Promise<Supplier[]> {
  try {
    const res = await fetch(`${BASE}/procurement/suppliers`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return [];
    return (await res.json()) as Supplier[];
  } catch {
    return [];
  }
}

/** Поставщики (клиент, через прокси /api). `null` при ошибке — чтобы не затереть SSR-данные. */
export async function fetchSuppliers(): Promise<Supplier[] | null> {
  try {
    const res = await fetch("/api/procurement/suppliers", { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as Supplier[];
  } catch {
    return null;
  }
}

/** Создать поставщика. Возвращает созданного или null при ошибке. */
export async function createSupplier(input: SupplierInput): Promise<Supplier | null> {
  try {
    const res = await fetch("/api/procurement/suppliers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return (await res.json()) as Supplier;
  } catch {
    return null;
  }
}

/** Изменить поставщика (частично). */
export async function updateSupplier(id: number, patch: Partial<SupplierInput>): Promise<Supplier | null> {
  try {
    const res = await fetch(`/api/procurement/suppliers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) return null;
    return (await res.json()) as Supplier;
  } catch {
    return null;
  }
}
