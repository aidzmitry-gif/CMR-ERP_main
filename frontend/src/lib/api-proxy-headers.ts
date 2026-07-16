// Headers for /api/[...path] -> FastAPI proxy.
// OIDC-ready Bearer forward + dev X-User-Roles; keep out of api.ts.

export interface BackendProxyHeaderOptions {
  /** Dev role from cookie aios_role. */
  devRole?: string;
  /** Future Keycloak httpOnly access token. */
  accessToken?: string;
}

/**
 * Build upstream headers for the backend.
 * - Forward incoming Authorization when present.
 * - Else inject Bearer from accessToken (OIDC skeleton).
 * - In dev also set X-User-Roles (ignored when auth_mode=oidc).
 */
export function buildBackendProxyHeaders(
  incoming: Headers,
  opts: BackendProxyHeaderOptions = {},
): Headers {
  const headers = new Headers(incoming);
  headers.delete("host");
  headers.delete("connection");

  const incomingAuth = incoming.get("authorization");
  if (incomingAuth) {
    headers.set("authorization", incomingAuth);
  } else if (opts.accessToken) {
    headers.set("authorization", Bearer );
  }

  if (opts.devRole) {
    headers.set("X-User-Roles", opts.devRole);
  }

  return headers;
}
