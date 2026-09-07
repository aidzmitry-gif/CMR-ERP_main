import { describe, expect, it } from "vitest";

import { ROLE_COOKIE, USER_COOKIE } from "@/lib/access";
import { applyOidcTokenCookies } from "@/lib/oidc-cookies";

function tokenWithRoles(roles: string[]): string {
  const payload = Buffer.from(JSON.stringify({ realm_access: { roles }, preferred_username: "new-user" })).toString("base64url");
  return `header.${payload}.signature`;
}

describe("applyOidcTokenCookies", () => {
  it("writes the original Cyrillic display name after token refresh", () => {
    const name = "Тест приглашений CRM";
    const payload = Buffer.from(JSON.stringify({ name, realm_access: { roles: ["onboarding"] } })).toString("base64url");
    const writes: Array<[string, string]> = [];
    applyOidcTokenCookies({ access_token: `header.${payload}.signature` }, (key, value) => writes.push([key, value]));
    expect(writes.find(([key]) => key === USER_COOKIE)).toEqual([USER_COOKIE, name]);
    expect(writes.find(([key]) => key === ROLE_COOKIE)).toEqual([ROLE_COOKIE, "onboarding"]);
  });

  it("сохраняет onboarding после refresh даже при технических Keycloak-ролях", () => {
    const writes: Array<[string, string]> = [];
    applyOidcTokenCookies(
      { access_token: tokenWithRoles(["uma_authorization", "sales", "onboarding"]) },
      (name, value) => writes.push([name, value]),
    );

    expect(writes.find(([name]) => name === ROLE_COOKIE)).toEqual([ROLE_COOKIE, "onboarding"]);
  });
});
