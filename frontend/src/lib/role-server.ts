// Серверный хелпер: текущая dev-сессия (логин + роль) из cookie. Импортируется ТОЛЬКО
// серверными компонентами (использует next/headers). Не тащить в клиентские компоненты и
// в api.ts (его тянут и клиентские модули) — отсюда отдельный файл.

import { cookies } from "next/headers";

import { DEFAULT_ROLE, ROLE_COOKIE, TOKEN_COOKIE, USER_COOKIE } from "@/lib/access";

/** Текущая роль из cookie `aios_role`; по умолчанию — полный доступ (director). */
export async function currentRole(): Promise<string> {
  return (await cookies()).get(ROLE_COOKIE)?.value ?? DEFAULT_ROLE;
}

/** Access token Keycloak (httpOnly), если уже выдан callback'ом. */
export async function currentAccessToken(): Promise<string | null> {
  return (await cookies()).get(TOKEN_COOKIE)?.value ?? null;
}

/** ФИО вошедшего сотрудника из cookie `aios_user` (URL-кодирован при логине). null — не вошёл. */
export async function currentUserName(): Promise<string | null> {
  const raw = (await cookies()).get(USER_COOKIE)?.value;
  if (!raw) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}
