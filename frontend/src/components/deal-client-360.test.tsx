import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DealClient360 } from "@/components/deal-client-360";
import type { CounterpartyCard } from "@/lib/reference-data";

// Компонент — async server component: сам ходит в /system/references/query (резолв имени →
// id) и /system/mdm/counterparty/{id} (карточка). Мокаем глобальный fetch по URL.
function stubFetch(
  handler: (url: string, init?: RequestInit) => Promise<Response> | Response,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => Promise.resolve(handler(url, init))),
  );
}

function queryResponse(rows: { id: number }[]): Response {
  return { ok: true, json: () => Promise.resolve({ result: rows }) } as Response;
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
  it("пустое имя компании — honest-empty, fetch вообще не вызывается", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(await DealClient360({ company: "   " }));
    expect(screen.getByText(/нет в MDM/)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("контрагент не резолвится в MDM (query вернул пусто) — honest-empty", async () => {
    stubFetch(() => queryResponse([]));
    render(await DealClient360({ company: "Незнакомая компания" }));
    expect(screen.getByText(/нет в MDM/)).toBeInTheDocument();
    expect(
      screen.getByText(/контрагент не найден в справочнике/),
    ).toBeInTheDocument();
  });

  it("query-запрос падает (500) — резолв даёт null, honest-empty без падения", async () => {
    stubFetch(() => ({ ok: false } as Response));
    render(await DealClient360({ company: "Компания" }));
    expect(screen.getByText(/нет в MDM/)).toBeInTheDocument();
  });

  it("резолвится и карточка найдена — показывает УНП, источник и контакт", async () => {
    stubFetch((url) =>
      url.includes("/system/mdm/counterparty/")
        ? ({ ok: true, json: () => Promise.resolve(cardFixture()) } as Response)
        : queryResponse([{ id: 42 }]),
    );
    render(await DealClient360({ company: "ООО Ромашка" }));
    expect(screen.getByText("192766048")).toBeInTheDocument();
    expect(screen.getByText("1С")).toBeInTheDocument(); // маппинг SOURCE_LABEL["1c"]
    expect(screen.getByText("Иван Иванов")).toBeInTheDocument();
    expect(screen.getByText(/\+375291234567/)).toBeInTheDocument();
    expect(screen.queryByText(/нет в MDM/)).not.toBeInTheDocument();
  });

  it("нет УНП — прочерк «—» вместо пустой строки", async () => {
    stubFetch((url) =>
      url.includes("/system/mdm/counterparty/")
        ? ({ ok: true, json: () => Promise.resolve(cardFixture({ unp: null })) } as Response)
        : queryResponse([{ id: 42 }]),
    );
    render(await DealClient360({ company: "ООО Ромашка" }));
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
        : queryResponse([{ id: 42 }]),
    );
    render(await DealClient360({ company: "ООО Ромашка" }));
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
        : queryResponse([{ id: 42 }]),
    );
    render(await DealClient360({ company: "ООО Ромашка" }));
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
        : queryResponse([{ id: 42 }]),
    );
    render(await DealClient360({ company: "ООО Ромашка" }));
    expect(screen.queryByText(/зв\./)).not.toBeInTheDocument();
  });

  it("роли пробрасываются заголовком X-User-Roles в оба запроса", async () => {
    let queryHeaders: HeadersInit | undefined;
    let cardHeaders: HeadersInit | undefined;
    stubFetch((url, init) => {
      if (url.includes("/system/mdm/counterparty/")) {
        cardHeaders = init?.headers;
        return { ok: true, json: () => Promise.resolve(cardFixture()) } as Response;
      }
      queryHeaders = init?.headers;
      return queryResponse([{ id: 42 }]);
    });
    render(await DealClient360({ company: "ООО Ромашка", roles: "rop,sales" }));
    expect((queryHeaders as Record<string, string>)["X-User-Roles"]).toBe("rop,sales");
    expect((cardHeaders as Record<string, string>)["X-User-Roles"]).toBe("rop,sales");
  });
});
