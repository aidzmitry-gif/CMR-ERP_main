import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DealClient360 } from "@/components/deal-client-360";
import type { CounterpartyCard } from "@/lib/reference-data";

vi.mock("@/lib/auth-headers-server", () => ({
  backendAuthHeaders: async (roles?: string) => ({
    Authorization: "Bearer synthetic-session-token",
    ...(roles ? { "X-User-Roles": roles } : {}),
  }),
}));

// Server component читает досье по ID, полученному из карточки сделки.
function stubFetch(
  handler: (url: string, init?: RequestInit) => Promise<Response> | Response,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => Promise.resolve(handler(url, init))),
  );
}



function cardFixture(over: Partial<CounterpartyCard> = {}): CounterpartyCard {
  return {
    id: 42,
    name: "ООО Ромашка",
    unp: "192766048",
    is_active: true,
    merged_into_id: null,
    provenance: {},
    aliases: [{ source: "1c", external_ref: "CP-1", created_at: "2026-01-01" }],
    merged_duplicates: [],
    contacts: [
      { id: 1, full_name: "Иван Иванов", phone: "+375291234567", email: null, is_primary: true },
    ],
    audit: [],
    touches: [],
    touch_summary: { calls: 3, deals: 2, messages: 5, last_contact: "2026-07-15T10:00:00Z" },
    ...over,
  } as CounterpartyCard;
}

afterEach(() => vi.unstubAllGlobals());

describe("DealClient360", () => {
  it("контрагент сделки не определён — honest-empty, fetch вообще не вызывается", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(await DealClient360({ counterpartyId: undefined }));
    expect(screen.getByText("Досье клиента пока недоступно.")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("сервер сделки не передал ID контрагента — honest-empty", async () => {
    stubFetch(() => { throw new Error("unexpected lookup"); });
    render(await DealClient360({ counterpartyId: undefined }));
    expect(screen.getByText("Досье клиента пока недоступно.")).toBeInTheDocument();
    expect(screen.queryByText(/MDM|отдельная сессия|после загрузки/)).toBeNull();
  });

  it("запрос досье падает (500) — ошибка загрузки вместо пустого досье", async () => {
    stubFetch(() => ({ ok: false } as Response));
    render(await DealClient360({ counterpartyId: 42 }));
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить досье клиента");
  });

  it("карточка по ID найдена — показывает УНП, источник и контакт", async () => {
    stubFetch((url) =>
      url.includes("/system/mdm/counterparty/")
        ? ({ ok: true, json: () => Promise.resolve(cardFixture()) } as Response)
        : new Response(null, { status: 404 }),
    );
    render(await DealClient360({ counterpartyId: 42 }));
    expect(screen.getByText("192766048")).toBeInTheDocument();
    expect(screen.getByText("1С")).toBeInTheDocument(); // маппинг SOURCE_LABEL["1c"]
    expect(screen.getByText("Иван Иванов")).toBeInTheDocument();
    expect(screen.getByText(/\+375291234567/)).toBeInTheDocument();
    expect(screen.queryByText("Досье клиента пока недоступно.")).not.toBeInTheDocument();
  });

  it("нет УНП — прочерк «—» вместо пустой строки", async () => {
    stubFetch((url) =>
      url.includes("/system/mdm/counterparty/")
        ? ({ ok: true, json: () => Promise.resolve(cardFixture({ unp: null })) } as Response)
        : new Response(null, { status: 404 }),
    );
    render(await DealClient360({ counterpartyId: 42 }));
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("неактивный и слитый контрагент — оба предупреждающих бейджа видны", async () => {
    stubFetch((url) =>
      url.includes("/system/mdm/counterparty/")
        ? ({
            ok: true,
            json: () =>
              Promise.resolve(cardFixture({ is_active: false, merged_into_id: 7 })),
          } as Response)
        : new Response(null, { status: 404 }),
    );
    render(await DealClient360({ counterpartyId: 42 }));
    expect(screen.getByText("неактивен")).toBeInTheDocument();
    expect(screen.getByText("слит")).toBeInTheDocument();
  });

  it("сводка касаний — точные числа звонков/сделок/сообщений и дата последнего контакта", async () => {
    stubFetch((url) =>
      url.includes("/system/mdm/counterparty/")
        ? ({
            ok: true,
            json: () =>
              Promise.resolve(
                cardFixture({
                  touch_summary: {
                    calls: 11,
                    deals: 4,
                    messages: 27,
                    last_contact: "2026-07-15T10:00:00Z",
                  },
                }),
              ),
          } as Response)
        : new Response(null, { status: 404 }),
    );
    render(await DealClient360({ counterpartyId: 42 }));
    expect(screen.getByText(/📞 11 зв\./)).toBeInTheDocument();
    expect(screen.getByText(/🤝 4 сд\./)).toBeInTheDocument();
    expect(screen.getByText(/💬 27 сообщ\./)).toBeInTheDocument();
    // last_contact обрезается до 10 символов (дата без времени)
    expect(screen.getByText(/2026-07-15/)).toBeInTheDocument();
  });

  it("touch_summary отсутствует (null) — блок сводки касаний не рендерится", async () => {
    stubFetch((url) =>
      url.includes("/system/mdm/counterparty/")
        ? ({
            ok: true,
            json: () => Promise.resolve(cardFixture({ touch_summary: null })),
          } as Response)
        : new Response(null, { status: 404 }),
    );
    render(await DealClient360({ counterpartyId: 42 }));
    expect(screen.queryByText(/зв\./)).not.toBeInTheDocument();
  });

  it("досье читается по точному ID с ролью и bearer без поиска по имени", async () => {

    let cardHeaders: HeadersInit | undefined;
    stubFetch((url, init) => {
      if (url.includes("/system/mdm/counterparty/")) {
        cardHeaders = init?.headers;
        return { ok: true, json: () => Promise.resolve(cardFixture()) } as Response;
      }
      throw new Error("unexpected name lookup");
    });
    render(await DealClient360({ counterpartyId: 42, roles: "rop,sales" }));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect((cardHeaders as Record<string, string>)["X-User-Roles"]).toBe("rop,sales");
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/system/mdm/counterparty/42"), expect.anything());
    expect((cardHeaders as Record<string, string>).Authorization).toBe("Bearer synthetic-session-token");
  });

  it.each([401, 403, 500])("отказ %s при чтении карточки отображается явно", async (status) => {
    stubFetch((url) => url.includes("/system/mdm/counterparty/")
      ? { ok: false, status } as Response : new Response(null, { status: 404 }));
    render(await DealClient360({ counterpartyId: 42 }));
    expect(screen.getByRole("alert")).toHaveTextContent(status === 401 ? "войдите снова" : status === 403 ? "Нет доступа" : "Не удалось загрузить");
  });
});
