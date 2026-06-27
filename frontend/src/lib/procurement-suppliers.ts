// Домен «Справочник поставщиков» поверх backend-API `/procurement/suppliers`.
// Supplier — профиль закупок (условия/срок/incoterms/статус); `unp` — soft-ref на MDM-контрагента
// (провенанс через <SourceTag>). SSR-загрузка ходит на BACKEND_URL, мутации — через прокси `/api`.

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export interface Supplier {
  id: number;
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

/** Поставщики (клиент, через прокси /api). */
export async function fetchSuppliers(): Promise<Supplier[]> {
  try {
    const res = await fetch("/api/procurement/suppliers", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as Supplier[];
  } catch {
    return [];
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
