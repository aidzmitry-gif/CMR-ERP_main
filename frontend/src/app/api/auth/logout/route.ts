// Dev-выход: чистит cookie сессии (роль + ФИО). Дальше фронт ведёт на /login.

import { cookies } from "next/headers";

import { ROLE_COOKIE, USER_COOKIE } from "@/lib/access";

export async function POST(): Promise<Response> {
  const jar = await cookies();
  jar.delete(ROLE_COOKIE);
  jar.delete(USER_COOKIE);
  return Response.json({ ok: true });
}
