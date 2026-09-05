// Dev-логин: по выбранному логину ставит httpOnly-cookie сессии (роль + ФИО).
// Пароля нет — это смена личности для dev, не защита (настоящий вход — Keycloak, часть 5).
// Источник пользователей — backend /system/users (единая матрица config/access.py).

import { cookies } from "next/headers";

import { ROLE_COOKIE, USER_COOKIE, type UserInfo } from "@/lib/access";
import { frontendAuthMode } from "@/lib/auth-mode";

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const YEAR = 60 * 60 * 24 * 365;

export async function POST(req: Request): Promise<Response> {
  if (frontendAuthMode() === "oidc") {
    return Response.json({ error: "Используйте корпоративный вход" }, { status: 403 });
  }
  const { username } = (await req.json()) as { username?: string };
  if (!username) return Response.json({ error: "username обязателен" }, { status: 400 });

  const res = await fetch(`${BASE}/system/users`, { cache: "no-store" });
  if (!res.ok) return Response.json({ error: "backend недоступен" }, { status: 502 });
  const users = ((await res.json()) as { users: UserInfo[] }).users;
  const user = users.find((u) => u.username === username);
  if (!user) return Response.json({ error: "неизвестный пользователь" }, { status: 404 });

  const jar = await cookies();
  const opts = { path: "/", httpOnly: true, sameSite: "lax" as const, maxAge: YEAR };
  jar.set(ROLE_COOKIE, user.role, opts);
  // Next cookies().set already encodes; do not encodeURIComponent (else %2520).
  jar.set(USER_COOKIE, user.full_name, opts);
  return Response.json({ ok: true, user });
}
