import { beforeEach, describe, expect, it, vi } from "vitest";

const jar = vi.hoisted(() => ({
  set: vi.fn(),
}));

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => jar),
}));

import { POST } from "@/app/api/auth/login/route";

beforeEach(() => {
  vi.clearAllMocks();
});

function request(body: unknown): Request {
  return new Request("http://localhost/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/auth/login", () => {
  it("валидирует username и отличает недоступный backend от неизвестного пользователя", async () => {
    expect((await POST(request({}))).status).toBe(400);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("down", { status: 503 })));
    expect((await POST(request({ username: "ivan" }))).status).toBe(502);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ users: [{ username: "petr", full_name: "Пётр", role: "sales" }] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    expect((await POST(request({ username: "ivan" }))).status).toBe(404);
  });

  it("ставит роль и display name для найденного dev-пользователя", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            users: [{ username: "ivan", full_name: "Иван Иванов", role: "sales", role_title: "Продажи" }],
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    const res = await POST(request({ username: "ivan" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ ok: true, user: { username: "ivan" } });
    expect(jar.set).toHaveBeenCalledTimes(2);
    expect(jar.set.mock.calls.map(([name]) => name)).toEqual(["aios_role", "aios_user"]);
  });
});
