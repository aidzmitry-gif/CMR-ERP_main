import { describe, expect, it } from "vitest";

import { buildBackendProxyHeaders } from "@/lib/api-proxy-headers";

describe("buildBackendProxyHeaders", () => {
  it("lets fetch calculate framing for the forwarded body", () => {
    const incoming = new Headers({ "content-length": "999", "transfer-encoding": "chunked", "content-type": "application/json" });
    const out = buildBackendProxyHeaders(incoming);
    expect(out.has("content-length")).toBe(false);
    expect(out.has("transfer-encoding")).toBe(false);
    expect(out.get("content-type")).toBe("application/json");
    expect(incoming.get("content-length")).toBe("999");
  });
  it("takes dev identity only from the server session and strips forged identity headers", () => {
    const incoming = new Headers({ "X-User": "foreign", "X-User-Roles": "director" });
    const scoped = buildBackendProxyHeaders(incoming, { devUsername: "manager", devRole: "sales" });
    expect(scoped.get("X-User")).toBe("manager");
    expect(scoped.get("X-User-Roles")).toBe("sales");
    const anonymous = buildBackendProxyHeaders(incoming);
    expect(anonymous.has("X-User")).toBe(false);
    expect(anonymous.has("X-User-Roles")).toBe(false);
  });
  it("пробрасывает Authorization и добавляет X-User-Roles для dev", () => {
    const incoming = new Headers({
      authorization: "Bearer incoming-token",
      host: "localhost:3000",
      connection: "keep-alive",
    });
    const out = buildBackendProxyHeaders(incoming, { devRole: "director", devUser: "kharkovich_d" });
    expect(out.get("authorization")).toBe("Bearer incoming-token");
    expect(out.get("X-User-Roles")).toBe("director");
    expect(out.get("X-User")).toBe("kharkovich_d");
    expect(out.has("host")).toBe(false);
    expect(out.has("connection")).toBe(false);
  });

  it("передаёт dev-идентификатор для scoped backend records", () => {
    const out = buildBackendProxyHeaders(new Headers(), { devUser: "accountant_1" });
    expect(out.get("X-User")).toBe("accountant_1");
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
