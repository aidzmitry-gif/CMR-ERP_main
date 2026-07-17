// Start Keycloak Authorization Code + PKCE flow.

import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import {
  OIDC_STATE_COOKIE,
  OIDC_VERIFIER_COOKIE,
  authorizeUrl,
  pkceChallenge,
  randomUrlSafe,
  resolveKeycloakConfig,
} from "@/lib/keycloak";

export async function GET(req: NextRequest): Promise<Response> {
  const cfg = resolveKeycloakConfig(req.url);
  if (!cfg) {
    return NextResponse.json(
      { error: "Keycloak не настроен (NEXT_PUBLIC_KEYCLOAK_ISSUER / CLIENT_ID)" },
      { status: 503 },
    );
  }

  const verifier = randomUrlSafe(32);
  const state = randomUrlSafe(16);
  const challenge = pkceChallenge(verifier);
  const jar = await cookies();
  const opts = { path: "/", httpOnly: true, sameSite: "lax" as const, maxAge: 600 };
  jar.set(OIDC_VERIFIER_COOKIE, verifier, opts);
  jar.set(OIDC_STATE_COOKIE, state, opts);

  const url = authorizeUrl({
    issuer: cfg.issuer,
    clientId: cfg.clientId,
    redirectUri: cfg.redirectUri,
    state,
    challenge,
  });
  return NextResponse.redirect(url);
}
