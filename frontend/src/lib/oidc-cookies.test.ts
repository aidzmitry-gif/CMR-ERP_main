import { describe, expect, it } from "vitest";

import { ROLE_COOKIE } from "@/lib/access";
import { applyOidcTokenCookies } from "@/lib/oidc-cookies";

function tokenWithRoles(roles: string[]): string {
  const payload = Buffer.from(JSON.stringify({ realm_access: { roles }, preferred_username: "new-user" })).toString("base64url");
  return `header.${payload}.signature`;
}

describe("applyOidcTokenCookies", () => {
  it("сохраняет onboarding после refresh даже при технических Keycloak-ролях", () => {
    const writes: Array<[string, string]> = [];
    applyOidcTokenCookies(
      { access_token: tokenWithRoles(["uma_authorization", "sales", "onboarding"]) },
      (name, value) => writes.push([name, value]),
    );

    expect(writes.find(([name]) => name === ROLE_COOKIE)).toEqual([ROLE_COOKIE, "onboarding"]);
  });
});
