export type InstanceOrganization = { id: number; name: string; unp: string; revision?: number };

export async function fetchInstanceOrganization(): Promise<InstanceOrganization> {
  let response: Response;
  try { response = await fetch("/api/system/instance-organization", { cache: "no-store" }); }
  catch { throw new Error("Не удалось загрузить юрлицо установки. Повторите загрузку."); }
  return readInstanceOrganization(response);
}

/** The same verified response contract is used by client and server readers. */
export async function readInstanceOrganization(response: Response): Promise<InstanceOrganization> {
  if (!response.ok) {
    const errors: Record<number, string> = {
      401: "Войдите в систему.",
      403: "Юрлицо установки недоступно. Проверьте настройку организации и права сотрудника.",
      409: "Настройка юрлица неоднозначна. Требуется проверка справочника организаций.",
      503: "Юрлицо установки не настроено или сервис недоступен. Проверьте настройки платформы.",
    };
    throw new Error(errors[response.status] || "Не удалось загрузить юрлицо установки.");
  }
  let data: unknown;
  try { data = await response.json(); }
  catch { throw new Error("Сервис вернул некорректное юрлицо установки."); }
  const context = data as { configuration?: unknown; revision?: unknown; organization?: Partial<InstanceOrganization> } | null;
  const org = context?.organization;
  if ((context?.configuration !== "AIOS_SELLER_UNP" && context?.configuration !== "platform_settings") || !org || typeof org.id !== "number"
    || !Number.isSafeInteger(org.id) || org.id <= 0 || typeof org.name !== "string"
    || typeof org.unp !== "string" || !/^[0-9]{9}$/.test(org.unp)
    || (context.configuration === "platform_settings" && (!Number.isSafeInteger(context.revision) || Number(context.revision) <= 0))) {
    throw new Error("Сервис вернул некорректное юрлицо установки.");
  }
  return context.configuration === "platform_settings"
    ? { ...org, revision: context.revision } as InstanceOrganization : org as InstanceOrganization;
}
