import { afterEach, describe, expect, it, vi } from "vitest";

import {
  accessTokenNeedsRefresh,
  displayNameFromAccessToken,
  peekJwtPayload,
  refreshAccessToken,
  rolesFromAccessToken,
  tokenEndpointIssuer,
} from "@/lib/keycloak-token";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function jwt(payload: Record<string, unknown>): string {
  return `header.${btoa(JSON.stringify(payload)).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_")}.sig`;
}

describe("keycloak-token", () => {
  it("выбирает internal issuer и проверяет expiry/роли/имя", () => {
    expect(tokenEndpointIssuer("https://public/realm/")).toBe("https://public/realm");
    vi.stubEnv("KEYCLOAK_INTERNAL_ISSUER", "http://keycloak:8080/realms/erp/");
    expect(tokenEndpointIssuer("https://public/realm/")).toBe("http://keycloak:8080/realms/erp");
    const token = jwt({ exp: 5000, realm_access: { roles: ["sales", 7, "director"] }, name: "Ivan" });
    expect(peekJwtPayload(token)).toMatchObject({ exp: 5000 });
    expect(peekJwtPayload("bad-token")).toBeNull();
    expect(peekJwtPayload("header.!invalid!.sig")).toBeNull();
    expect(accessTokenNeedsRefresh(null, 60, 1000)).toBe(true);
    expect(accessTokenNeedsRefresh(token, 60, 1000)).toBe(false);
    expect(accessTokenNeedsRefresh(token, 60, 4940)).toBe(true);
    expect(rolesFromAccessToken(token)).toEqual(["sales", "director"]);
    expect(displayNameFromAccessToken(token)).toBe("Ivan");
    expect(displayNameFromAccessToken("bad-token")).toBe("oidc-user");
  });

  it("обновляет access token и безопасно возвращает null на HTTP/сетевой ошибке", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ access_token: "new", refresh_token: "next" }) })
      .mockResolvedValueOnce({ ok: false })
      .mockRejectedValueOnce(new Error("offline"));
    vi.stubGlobal("fetch", fetchMock);
    const opts = { issuer: "https://public/realm/", clientId: "erp", refreshToken: "refresh" };
    await expect(refreshAccessToken(opts)).resolves.toEqual({ access_token: "new", refresh_token: "next" });
    await expect(refreshAccessToken(opts)).resolves.toBeNull();
    await expect(refreshAccessToken(opts)).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://public/realm/protocol/openid-connect/token",
      expect.objectContaining({ method: "POST", cache: "no-store" }),
    );
  });
});
