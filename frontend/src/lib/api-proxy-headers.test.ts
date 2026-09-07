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

  it.each(["Bearer client", "bearer client", "Bearer"])("явный %s имеет приоритет над cookie, включая некорректный Bearer", (authorization) => {
    const incoming = new Headers({ authorization });
    const out = buildBackendProxyHeaders(incoming, { accessToken: "cookie-jwt" });
    expect(out.get("authorization")).toBe(authorization);
  });

  it("использует OIDC cookie, когда браузер передаёт Basic Auth входного прокси", () => {
    const incoming = new Headers({ authorization: "Basic synthetic-edge-credentials" });
    const out = buildBackendProxyHeaders(incoming, { accessToken: "cookie-jwt" });
    expect(out.get("authorization")).toBe("Bearer cookie-jwt");
    expect(incoming.get("authorization")).toBe("Basic synthetic-edge-credentials");
  });

  it("не передаёт Basic credentials backend без OIDC-сессии", () => {
    const incoming = new Headers({ authorization: "Basic synthetic-edge-credentials" });
    const out = buildBackendProxyHeaders(incoming);
    expect(out.has("authorization")).toBe(false);
  });
});
