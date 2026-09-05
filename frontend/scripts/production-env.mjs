function publicHttpsUrl(value, name, { originOnly = false } = {}) {
  let url;
  try {
    url = new URL(value);
  } catch {
    return `${name} must be an absolute HTTPS URL`;
  }
  if (url.protocol !== "https:" || !url.hostname) {
    return `${name} must be an absolute HTTPS URL`;
  }
  if (url.username || url.password) {
    return `${name} must not contain embedded credentials`;
  }
  if (url.search || url.hash) {
    return `${name} must not contain a query string or fragment`;
  }
  if (originOnly && url.pathname !== "/") {
    return `${name} must be an origin without a path`;
  }
  return null;
}

/** Validate the public settings that Next embeds into browser bundles. */
export function productionEnvErrors(env = process.env) {
  const errors = [];
  if ((env.NEXT_PUBLIC_AUTH_MODE ?? "").trim().toLowerCase() !== "oidc") {
    errors.push("NEXT_PUBLIC_AUTH_MODE must be oidc");
  }

  const issuer = (env.NEXT_PUBLIC_KEYCLOAK_ISSUER ?? "").trim();
  if (!issuer) errors.push("NEXT_PUBLIC_KEYCLOAK_ISSUER is required");
  else {
    const error = publicHttpsUrl(issuer, "NEXT_PUBLIC_KEYCLOAK_ISSUER");
    if (error) errors.push(error);
  }

  const clientId = (env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID ?? "").trim();
  if (!clientId) errors.push("NEXT_PUBLIC_KEYCLOAK_CLIENT_ID is required");
  else if (/\s/.test(clientId)) errors.push("NEXT_PUBLIC_KEYCLOAK_CLIENT_ID must not contain whitespace");

  const appOrigin = (env.NEXT_PUBLIC_APP_ORIGIN ?? "").trim();
  if (appOrigin) {
    const error = publicHttpsUrl(appOrigin, "NEXT_PUBLIC_APP_ORIGIN", { originOnly: true });
    if (error) errors.push(error);
  }
  return errors;
}
