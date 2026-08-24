// Доступ ролей к модулям. Единый источник матрицы — backend (`config/access.py`),
// фронт лишь читает её через `/system/access` и прячет недоступные пункты сайдбара.
// Реального логина пока нет: текущая роль хранится в cookie `aios_role` (dev-переключатель),
// прокси `/api/[...path]` пробрасывает её в backend заголовком `X-User-Roles`.

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

/** Имя cookie с текущей dev-ролью. */
export const ROLE_COOKIE = "aios_role";
/** Имя cookie с логином вошедшего сотрудника (dev-логин). */
export const USER_COOKIE = "aios_user";
/** Зарезервировано под httpOnly access token Keycloak; пока не ставится (часть 5 OIDC). */
export const TOKEN_COOKIE = "aios_access_token";
/** Роль по умолчанию (полный доступ) — fallback, если роль в cookie отсутствует. */
export const DEFAULT_ROLE = "director";

export interface UserInfo {
  username: string;
  full_name: string;
  role: string;
  role_title: string;
}

/** Список сотрудников для экрана входа (dev-логин). Источник — backend `/system/users`. */
export async function fetchUsers(): Promise<UserInfo[]> {
  try {
    const res = await fetch(`${BASE}/system/users`, { cache: "no-store" });
    if (!res.ok) return [];
    return ((await res.json()) as { users: UserInfo[] }).users;
  } catch {
    return [];
  }
}

export interface RoleInfo {
  slug: string;
  title: string;
}

export interface AccessData {
  /** роль → список UI-слагов доступных модулей */
  matrix: Record<string, string[]>;
  /** все роли для dev-переключателя (в порядке отображения) */
  roles: RoleInfo[];
  /** роли текущего запроса (по заголовку), для справки */
  current_roles: string[];
}

/** Подтянуть матрицу доступа с backend под конкретную роль (SSR). null — backend недоступен. */
export async function fetchAccess(role: string): Promise<AccessData | null> {
  try {
    const res = await fetch(`${BASE}/system/access`, {
      cache: "no-store",
      headers: { "X-User-Roles": role },
    });
    if (!res.ok) return null;
    return (await res.json()) as AccessData;
  } catch {
    return null;
  }
}

/** Доступные слаги для роли из матрицы; неизвестная роль → пусто. */
export function slugsForRole(data: AccessData, role: string): string[] {
  return data.matrix[role] ?? [];
}
