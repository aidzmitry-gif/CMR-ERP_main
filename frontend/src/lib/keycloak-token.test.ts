import { afterEach, describe, expect, it, vi } from "vitest";

import { accessTokenNeedsRefresh, displayNameFromAccessToken, peekJwtPayload } from "@/lib/keycloak-token";

afterEach(() => vi.unstubAllGlobals());

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
  it.each(["Тест приглашений CRM", "Дмитрий Ёжиков", "Zoë 李 🚀"])("preserves UTF-8 name %s with browser decoding", (name) => {
    const payload = Buffer.from(JSON.stringify({ name, realm_access: { roles: ["onboarding"] } })).toString("base64url");
    expect(typeof atob).toBe("function");
    expect(displayNameFromAccessToken(`header.${payload}.signature`)).toBe(name);
    expect(peekJwtPayload(`header.${payload}.signature`)?.realm_access).toEqual({ roles: ["onboarding"] });
  });

  it("preserves UTF-8 names without browser atob", () => {
    const payload = Buffer.from(JSON.stringify({ name: "Тест приглашений CRM" })).toString("base64url");
    vi.stubGlobal("atob", undefined);
    expect(displayNameFromAccessToken(`header.${payload}.signature`)).toBe("Тест приглашений CRM");
  });

  it("returns null for malformed payloads", () => {
    expect(peekJwtPayload("header.%%%.signature")).toBeNull();
    expect(peekJwtPayload("header.bm90LWpzb24.signature")).toBeNull();
  });

  it("reads exp", () => {
    const exp = 1_700_000_123;
    expect(peekJwtPayload(jwtWithExp(exp))?.exp).toBe(exp);
  });
});
