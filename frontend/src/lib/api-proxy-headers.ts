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
 * - Forward an explicit incoming Bearer, otherwise use the OIDC access cookie.
 * - Do not forward ingress Basic Auth credentials to the application backend.
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
  headers.delete("authorization");
  if (incomingAuth && /^Bearer(?:\s|$)/i.test(incomingAuth)) {
    headers.set("authorization", incomingAuth);
  } else if (opts.accessToken) {
    headers.set("authorization", "Bearer " + opts.accessToken);
  }

  if (opts.devRole) {
    headers.set("X-User-Roles", opts.devRole);
  }

  return headers;
}
