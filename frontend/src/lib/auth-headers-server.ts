// Server-only: headers for SSR fetches to FastAPI (BACKEND_URL direct).
// Do not import from client components or shared libs pulled by the browser.

import { cookies } from "next/headers";

import { DEFAULT_ROLE, ROLE_COOKIE, TOKEN_COOKIE } from "@/lib/access";
import { frontendAuthMode } from "@/lib/auth-mode";

/**
 * Auth headers for backend SSR calls.
 * - Always attach X-User-Roles in ``dev`` (header-trust).
 * - Attach Authorization Bearer when ``aios_access_token`` cookie is set.
 * - In ``oidc`` mode prefer Bearer; still send X-User-Roles if present (backend ignores it).
 */
export async function backendAuthHeaders(
  roleOverride?: string,
): Promise<Record<string, string>> {
  const jar = await cookies();
  const role = roleOverride ?? jar.get(ROLE_COOKIE)?.value ?? DEFAULT_ROLE;
  const token = jar.get(TOKEN_COOKIE)?.value;
  const mode = frontendAuthMode();
  const headers: Record<string, string> = {};

  if (token) {
    headers.Authorization = "Bearer " + token;
  }
  if (mode === "dev" || !token) {
    headers["X-User-Roles"] = role;
  } else if (role) {
    // oidc + token: optional hint for dual-run diagnostics (backend ignores in oidc)
    headers["X-User-Roles"] = role;
  }
  return headers;
}

export async function currentAccessToken(): Promise<string | null> {
  return (await cookies()).get(TOKEN_COOKIE)?.value ?? null;
}
