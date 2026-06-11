// Серверный хелпер: текущая dev-роль из cookie. Импортируется ТОЛЬКО серверными
// компонентами (использует next/headers). Не тащить в клиентские компоненты и в api.ts
// (его тянут и клиентские модули) — отсюда отдельный файл.

import { cookies } from "next/headers";

import { DEFAULT_ROLE, ROLE_COOKIE } from "@/lib/access";

/** Текущая роль из cookie `aios_role`; по умолчанию — полный доступ (director). */
export async function currentRole(): Promise<string> {
  return (await cookies()).get(ROLE_COOKIE)?.value ?? DEFAULT_ROLE;
}
