export type InstanceOrganization = { id: number; name: string; unp: string };

export async function fetchInstanceOrganization(): Promise<InstanceOrganization> {
  let response: Response;
  try { response = await fetch("/api/system/instance-organization", { cache: "no-store" }); }
  catch { throw new Error("Не удалось загрузить юрлицо установки. Повторите загрузку."); }
  if (!response.ok) {
    const errors: Record<number, string> = {
      401: "Войдите в систему.",
      403: "Юрлицо установки недоступно. Проверьте настройку организации и права сотрудника.",
      409: "Настройка юрлица неоднозначна. Требуется проверка справочника организаций.",
      503: "Юрлицо установки не настроено или сервис недоступен. Проверьте настройки сервера.",
    };
    throw new Error(errors[response.status] || "Не удалось загрузить юрлицо установки.");
  }
  let data: unknown;
  try { data = await response.json(); }
  catch { throw new Error("Сервис вернул некорректное юрлицо установки."); }
  const context = data as { configuration?: unknown; organization?: Partial<InstanceOrganization> } | null;
  const org = context?.organization;
  if (context?.configuration !== "AIOS_SELLER_UNP" || !org || typeof org.id !== "number"
    || !Number.isSafeInteger(org.id) || org.id <= 0 || typeof org.name !== "string"
    || typeof org.unp !== "string" || !/^[0-9]{9}$/.test(org.unp)) {
    throw new Error("Сервис вернул некорректное юрлицо установки.");
  }
  return org as InstanceOrganization;
}
