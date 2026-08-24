// Заголовки для прокси `/api/[...path]` → backend FastAPI.
// Вынесено из route.ts: OIDC-задел (Bearer) + dev-роль (X-User-Roles) без правок api.ts.

export interface BackendProxyHeaderOptions {
  /** Dev-роль из cookie `aios_role`; backend auth_mode=dev читает X-User-Roles. */
  devRole?: string;
  /** Access token из httpOnly cookie (будущий Keycloak login); inject Bearer если нет Authorization. */
  accessToken?: string;
}

/** Минимальный контракт входящих заголовков (NextRequest.headers, fetch Response, …). */
export type IncomingHeaderSource = { get(name: string): string | null };

/**
 * Собирает заголовки апстрим-запроса к backend.
 * - Пробрасывает входящий Authorization (если клиент уже шлёт Bearer).
 * - Иначе, при наличии accessToken, ставит Authorization: Bearer (OIDC-скелет).
 * - В dev-режиме дополнительно ставит X-User-Roles (не ломает oidc: backend в oidc игнорирует заголовок).
 */
export function buildBackendProxyHeaders(
  incoming: IncomingHeaderSource & Iterable<[string, string]>,
  opts: BackendProxyHeaderOptions = {},
): Headers {
  const headers = new Headers(incoming);
  headers.delete("host");
  headers.delete("connection");

  const incomingAuth = incoming.get("authorization");
  if (incomingAuth) {
    headers.set("authorization", incomingAuth);
  } else if (opts.accessToken) {
    headers.set("authorization", `Bearer ${opts.accessToken}`);
  }

  if (opts.devRole) {
    headers.set("X-User-Roles", opts.devRole);
  }

  return headers;
}
