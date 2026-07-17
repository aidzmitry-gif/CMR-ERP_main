// Выход: чистит cookie сессии (роль + ФИО + OIDC токены). Дальше фронт ведёт на /login.

import { cookies } from "next/headers";

import { ROLE_COOKIE, TOKEN_COOKIE, USER_COOKIE } from "@/lib/access";
import { REFRESH_COOKIE } from "@/lib/keycloak";

export async function POST(): Promise<Response> {
  const jar = await cookies();
  jar.delete(ROLE_COOKIE);
  jar.delete(USER_COOKIE);
  jar.delete(TOKEN_COOKIE);
  jar.delete(REFRESH_COOKIE);
  return Response.json({ ok: true });
}
