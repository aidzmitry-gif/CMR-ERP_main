import { describe, expect, it } from "vitest";

import { accessTokenNeedsRefresh, peekJwtPayload } from "@/lib/keycloak-token";

function jwtWithExp(exp: number): string {
  const header = Buffer.from(JSON.stringify({ alg: "none" })).toString("base64url");
  const payload = Buffer.from(JSON.stringify({ exp, preferred_username: "t" })).toString(
    "base64url",
  );
  return `${header}.${payload}.sig`;
}

describe("accessTokenNeedsRefresh", () => {
  it("true when missing", () => {
    expect(accessTokenNeedsRefresh(null)).toBe(true);
    expect(accessTokenNeedsRefresh(undefined)).toBe(true);
    expect(accessTokenNeedsRefresh("")).toBe(true);
  });

  it("false when exp is comfortably ahead", () => {
    const now = 1_700_000_000;
    expect(accessTokenNeedsRefresh(jwtWithExp(now + 600), 60, now)).toBe(false);
  });

  it("true when within skew", () => {
    const now = 1_700_000_000;
    expect(accessTokenNeedsRefresh(jwtWithExp(now + 30), 60, now)).toBe(true);
  });

  it("true when already expired", () => {
    const now = 1_700_000_000;
    expect(accessTokenNeedsRefresh(jwtWithExp(now - 1), 60, now)).toBe(true);
  });
});

describe("peekJwtPayload", () => {
  it("reads exp", () => {
    const exp = 1_700_000_123;
    expect(peekJwtPayload(jwtWithExp(exp))?.exp).toBe(exp);
  });
});
