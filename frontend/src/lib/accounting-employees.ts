export type AccountingEmployee = {
  employee: string;
  employee_id: string;
  employment_binding_id: string;
  employee_contract_ref: string;
  employee_binding_revision: string;
  employee_binding_digest: string;
  department: string;
};

export async function searchAccountingEmployees(
  org: string,
  on: string,
  term: string,
): Promise<AccountingEmployee[]> {
  const book = Number(org);
  const query = term.trim();
  if (!Number.isSafeInteger(book) || book <= 0 || !/^\d{4}-\d{2}-\d{2}$/.test(on) || !query) return [];
  const response = await fetch(
    `/api/accounting/organizations/${book}/manual-employees?on=${encodeURIComponent(on)}&q=${encodeURIComponent(query)}`,
    { cache: "no-store" },
  );
  if (!response.ok) throw new Error(`Справочник сотрудников недоступен (${response.status})`);
  const page: unknown = await response.json();
  if (!page || typeof page !== "object"
      || (page as { organization_id?: unknown }).organization_id !== book
      || (page as { on?: unknown }).on !== on
      || !Array.isArray((page as { items?: unknown }).items))
    throw new Error("Справочник сотрудников ответил для другой организации или даты");
  const items = (page as { items: AccountingEmployee[] }).items;
  if (items.length > 50 || items.some(item => !item
      || typeof item.employee !== "string" || !item.employee.trim()
      || typeof item.employee_id !== "string" || !/^[1-9]\d*$/.test(item.employee_id)
      || typeof item.employment_binding_id !== "string" || !/^[1-9]\d*$/.test(item.employment_binding_id)
      || typeof item.employee_contract_ref !== "string" || !item.employee_contract_ref.trim()
      || typeof item.employee_binding_revision !== "string" || !/^[1-9]\d*$/.test(item.employee_binding_revision)
      || typeof item.employee_binding_digest !== "string" || !/^[0-9a-f]{64}$/.test(item.employee_binding_digest)
      || typeof item.department !== "string"))
    throw new Error("Справочник сотрудников вернул некорректные записи");
  return items;
}
