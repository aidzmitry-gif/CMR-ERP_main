// Доступ ролей к модулям. Единый источник матрицы — backend (`config/access.py`),
// фронт лишь читает её через `/system/access` и прячет недоступные пункты сайдбара.
// Реального логина пока нет: текущая роль хранится в cookie `aios_role` (dev-переключатель),
// прокси `/api/[...path]` пробрасывает её в backend заголовком `X-User-Roles`.

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

/** Имя cookie с текущей dev-ролью. */
export const ROLE_COOKIE = "aios_role";
/** Роль по умолчанию (полный доступ) — пока пользователь не выбрал другую. */
export const DEFAULT_ROLE = "director";

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
