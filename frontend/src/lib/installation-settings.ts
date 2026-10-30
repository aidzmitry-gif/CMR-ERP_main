import type { InstanceOrganization } from "./instance-organization";

export type InstallationSettings = {
  organization: InstanceOrganization | null;
  revision: number;
  configuration: "platform_settings" | "AIOS_SELLER_UNP" | null;
  can_manage: boolean;
  organizations: InstanceOrganization[];
};
export type InstallationCommand = { organization_id: number; expected_revision: number; request_id: string };
export class InstallationSettingsError extends Error {
  constructor(message: string, readonly uncertain: boolean, readonly status?: number) { super(message); }
}
const validOrganization = (value: unknown): value is InstanceOrganization => {
  const row = value as Partial<InstanceOrganization> | null;
  return !!row && Number.isSafeInteger(row.id) && Number(row.id) > 0
    && typeof row.name === "string" && !!row.name.trim()
    && typeof row.unp === "string" && /^[0-9]{9}$/.test(row.unp);
};
async function request(body?: InstallationCommand): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch("/api/system/installation-organization", {
      cache: "no-store", ...(body ? { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
    });
  } catch { throw new InstallationSettingsError("Не удалось получить подтверждение настройки.", !!body); }
  let data: unknown;
  try { data = await response.json(); }
  catch { throw new InstallationSettingsError("Сервис настройки вернул некорректный ответ.", !!body && (response.ok || response.status >= 500)); }
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new InstallationSettingsError(typeof detail === "string" ? detail : `Ошибка настройки: ${response.status}.`, !!body && response.status >= 500, response.status);
  }
  return data;
}
export async function loadInstallationSettings(): Promise<InstallationSettings> {
  const data = await request() as InstallationSettings | null;
  if (!data || !Number.isSafeInteger(data.revision) || data.revision < 0 || typeof data.can_manage !== "boolean"
    || ![null, "platform_settings", "AIOS_SELLER_UNP"].includes(data.configuration)
    || (data.organization !== null && !validOrganization(data.organization))
    || !Array.isArray(data.organizations) || !data.organizations.every(validOrganization)
    || new Set(data.organizations.map(row => row.id)).size !== data.organizations.length) {
    throw new InstallationSettingsError("Не удалось проверить настройку юрлица.", false);
  }
  return data;
}
export async function saveInstallationSettings(command: InstallationCommand) {
  const data = await request(command) as { organization?: unknown; revision?: unknown; configuration?: unknown } | null;
  if (!data || !validOrganization(data.organization) || data.organization.id !== command.organization_id
    || data.revision !== command.expected_revision + 1 || data.configuration !== "platform_settings") {
    throw new InstallationSettingsError("Сохранение юрлица не подтверждено сервером.", true);
  }
  return { organization: data.organization, revision: data.revision as number };
}
