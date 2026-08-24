import { describe, expect, it } from "vitest";

import { buildBackendProxyHeaders } from "@/lib/api-proxy-headers";

describe("buildBackendProxyHeaders", () => {
  it("пробрасывает Authorization и добавляет X-User-Roles для dev", () => {
    const incoming = new Headers({
      authorization: "Bearer incoming-token",
      host: "localhost:3000",
      connection: "keep-alive",
    });
    const out = buildBackendProxyHeaders(incoming, { devRole: "director" });
    expect(out.get("authorization")).toBe("Bearer incoming-token");
    expect(out.get("X-User-Roles")).toBe("director");
    expect(out.has("host")).toBe(false);
    expect(out.has("connection")).toBe(false);
  });

  it("inject Bearer из accessToken только если Authorization не пришёл", () => {
    const incoming = new Headers();
    const out = buildBackendProxyHeaders(incoming, { accessToken: "cookie-jwt", devRole: "sales" });
    expect(out.get("authorization")).toBe("Bearer cookie-jwt");
    expect(out.get("X-User-Roles")).toBe("sales");
  });

  it("входящий Authorization имеет приоритет над accessToken", () => {
    const incoming = new Headers({ authorization: "Bearer client" });
    const out = buildBackendProxyHeaders(incoming, { accessToken: "cookie-jwt" });
    expect(out.get("authorization")).toBe("Bearer client");
  });
});
