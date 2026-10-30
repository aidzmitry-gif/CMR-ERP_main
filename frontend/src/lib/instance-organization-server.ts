// Server-only reader: receives the authenticated SSR headers, never browser hints.
import { readInstanceOrganization } from "./instance-organization";

export async function fetchInstanceOrganizationServer(headers: Record<string, string>) {
  let response: Response;
  try {
    response = await fetch(`${process.env.BACKEND_URL ?? "http://127.0.0.1:8000"}/system/instance-organization`, {
      cache: "no-store", headers,
    });
  } catch { throw new Error("Ошибка сети при загрузке юрлица установки."); }
  return readInstanceOrganization(response);
}
