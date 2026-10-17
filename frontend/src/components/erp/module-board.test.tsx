import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModuleBoard } from "@/components/erp/module-board";

type FetchCall = { url: string; init?: RequestInit };
type FetchHandler = (url: string, init?: RequestInit) => Promise<Response>;

let calls: FetchCall[];

function response(value: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn(async () => value),
  } as unknown as Response;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function installFetch(handler: FetchHandler) {
  const mock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    return handler(url, init);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const campaign = {
  id: 1,
  name: "Кампания",
  channel: "email",
  status: "new",
  budget: "10.00",
  leads: 0,
};
const campaignColumns = [
  { key: "name", label: "Кампания" },
  { key: "channel", label: "Канал" },
  { key: "status", label: "Статус" },
  { key: "budget", label: "Бюджет" },
  { key: "leads", label: "Лиды" },
];
const campaignFields = [
  { key: "name", label: "Кампания" },
  { key: "channel", label: "Канал" },
  { key: "budget", label: "Бюджет", type: "number" as const, default: 0 },
  { key: "leads", label: "Лиды", type: "number" as const, default: 0 },
];
const baseProps: ComponentProps<typeof ModuleBoard> = {
  title: "Маркетинг",
  endpoint: "/marketing/campaigns",
  columns: campaignColumns,
  fields: campaignFields,
};
function board(overrides: Partial<ComponentProps<typeof ModuleBoard>> = {}) {
  return <ModuleBoard {...baseProps} {...overrides} />;
}

function methodOf(init?: RequestInit): string {
  return init?.method ?? "GET";
}
function callsFor(method: string, url?: string): FetchCall[] {
  return calls.filter((call) => methodOf(call.init) === method && (!url || call.url === url));
}

beforeEach(() => {
  calls = [];
  installFetch(async (url, init) => {
    const method = methodOf(init);
    if (method === "GET") {
      if (url === "/api/service/tickets") {
        return response({ id: 1, customer: "Клиент", subject: "Обращение", status: "new" } as unknown);
      }
      if (url === "/api/procurement/requests") {
        return response({ id: 1, name: "Заявка", status: "new" } as unknown);
      }
      return response([campaign]);
    }
    if (method === "PATCH") {
      const body = JSON.parse(String(init?.body)) as { status?: string };
      return response({ ...campaign, status: body.status });
    }
    if (url.endsWith("/launch")) return response(campaign);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    if (url === "/api/service/tickets") {
      return response({ id: 2, customer: body.customer, subject: body.subject, status: "new" }, 201);
    }
    return response({ ...campaign, id: 2, name: body.name ?? "Новая кампания" }, 201);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ModuleBoard", () => {
  it("грузит строки и создаёт запись с точным URL и телом POST", async () => {
    let getCount = 0;
    installFetch(async (url, init) => {
      if (methodOf(init) === "GET") {
        getCount += 1;
        return response(getCount === 1 ? [campaign] : [{ ...campaign, id: 2, name: "Новая кампания" }]);
      }
      return response({ ...campaign, id: 2, name: "Новая кампания" }, 201);
    });
    render(board());
    expect(await screen.findByRole("cell", { name: "Кампания" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Кампания"), { target: { value: "Новая кампания" } });
    fireEvent.change(screen.getByLabelText("Канал"), { target: { value: "email" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByRole("cell", { name: "Новая кампания" })).toBeInTheDocument();
    const post = callsFor("POST", "/api/marketing/campaigns");
    expect(post).toHaveLength(1);
    expect(post[0].init?.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(String(post[0].init?.body))).toEqual({
      name: "Новая кампания",
      channel: "email",
      budget: 0,
      leads: 0,
    });
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(2);
  });

  it("смена статуса подтверждается ответом с тем же ID и обновлённым списком", async () => {
    let getCount = 0;
    installFetch(async (_url, init) => {
      if (methodOf(init) === "GET") {
        getCount += 1;
        return response([{ ...campaign, status: getCount > 1 ? "done" : "new" }]);
      }
      const body = JSON.parse(String(init?.body)) as { status: string };
      return response({ ...campaign, status: body.status });
    });
    render(board({
      title: "Закупки",
      endpoint: "/procurement/requests",
      columns: [{ key: "name", label: "Имя" }, { key: "status", label: "Статус" }],
      fields: [{ key: "name", label: "Имя" }],
      statusKey: "status",
      statusFlow: ["new", "done"],
      patchPath: "/procurement/requests",
    }));

    fireEvent.click(await screen.findByRole("button", { name: "new" }));
    expect(await screen.findByRole("button", { name: "done" })).toBeInTheDocument();
    const patch = callsFor("PATCH", "/api/procurement/requests/1");
    expect(patch).toHaveLength(1);
    expect(patch[0].init?.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(String(patch[0].init?.body))).toEqual({ status: "done" });
    expect(callsFor("GET", "/api/procurement/requests")).toHaveLength(2);
  });

  it("действие сохраняет введённое числовое поле и шлёт прежний POST", async () => {
    render(board({
      fields: [...campaignFields, { key: "target", label: "Цель числом", type: "number", default: 0 }],
      action: { label: "Запустить", path: "/marketing/campaigns/{id}/launch" },
    }));
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Цель числом"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Запустить" }));

    await waitFor(() => expect(callsFor("POST", "/api/marketing/campaigns/1/launch")).toHaveLength(1));
    expect(callsFor("POST", "/api/marketing/campaigns/1/launch")[0].init?.body).toBeUndefined();
    expect(screen.getByLabelText("Цель числом")).toHaveValue(5);
  });

  it("[LOAD-EMPTY] показывает успешный пустой список как пустой", async () => {
    installFetch(async () => response([]));
    render(board());
    expect(await screen.findByText("Записей пока нет")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("[LOAD-HTTP] показывает HTTP-ошибку и повторяет GET того же endpoint", async () => {
    let getCount = 0;
    installFetch(async () => {
      getCount += 1;
      return getCount === 1 ? response({ detail: "unavailable" }, 503) : response([campaign]);
    });
    render(board());
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503");
    expect(screen.queryByText("Записей пока нет")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByRole("cell", { name: "Кампания" })).toBeInTheDocument();
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(2);
  });

  it("[LOAD-NETWORK] показывает сетевую ошибку и позволяет повторить текущий GET", async () => {
    let getCount = 0;
    installFetch(async () => {
      getCount += 1;
      if (getCount === 1) throw new Error("offline");
      return response([campaign]);
    });
    render(board());
    expect(await screen.findByRole("alert")).toHaveTextContent("Проверьте соединение");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByRole("cell", { name: "Кампания" })).toBeInTheDocument();
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(2);
  });

  it("[LOAD-NONARRAY] не принимает объект вместо массива и не показывает пустой список", async () => {
    installFetch(async () => response({ id: 1 }));
    render(board());
    expect(await screen.findByRole("alert")).toHaveTextContent("некорректный список");
    expect(screen.getByText("Список недоступен")).toBeInTheDocument();
    expect(screen.queryByText("Записей пока нет")).not.toBeInTheDocument();
  });

  it("[LOAD-INVALID-ID] отклоняет строку без безопасного положительного ID", async () => {
    installFetch(async () => response([{ ...campaign, id: 0 }]));
    render(board());
    expect(await screen.findByRole("alert")).toHaveTextContent("некорректный список");
    expect(screen.queryByRole("cell", { name: "Кампания" })).not.toBeInTheDocument();
    expect(screen.getByText("Список недоступен")).toBeInTheDocument();
  });

  it("[LOAD-MISSING-COLUMNS] rejects a row with a valid ID but missing configured columns", async () => {
    installFetch(async () => response([{ id: 2 }]));
    render(board());
    expect(await screen.findByRole("alert")).toHaveTextContent("некорректный список");
    expect(screen.queryByRole("cell", { name: "Кампания" })).not.toBeInTheDocument();
    expect(screen.getByText("Список недоступен")).toBeInTheDocument();
    expect(screen.queryByText("Записей пока нет")).not.toBeInTheDocument();
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[REFRESH-STALE] сохраняет старые строки и блокирует запись при ошибке обновления", async () => {
    let getCount = 0;
    installFetch(async () => {
      getCount += 1;
      return getCount === 1 ? response([campaign]) : response({ detail: "failed" }, 503);
    });
    render(board());
    expect(await screen.findByRole("cell", { name: "Кампания" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503");
    expect(screen.getByRole("cell", { name: "Кампания" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Отображаются предыдущие данные; запись заблокирована до успешного обновления.");
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
    expect(screen.queryByText("Записей пока нет")).not.toBeInTheDocument();
  });

  it("[ENDPOINT-ABA-GET] игнорирует старый ответ A после перехода A → B → A", async () => {
    const firstA = deferred<Response>();
    let aGets = 0;
    installFetch(async (url) => {
      if (url === "/api/a") {
        aGets += 1;
        if (aGets === 1) return firstA.promise;
        return response([{ id: 3, name: "A-current" }]);
      }
      return response([{ id: 2, name: "B-current" }]);
    });
    const props = {
      ...baseProps,
      columns: [{ key: "name", label: "Имя" }],
      fields: [{ key: "name", label: "Имя" }],
    };
    const view = render(board({ ...props, endpoint: "/a", title: "A" }));
    await waitFor(() => expect(callsFor("GET", "/api/a")).toHaveLength(1));

    view.rerender(board({ ...props, endpoint: "/b", title: "B" }));
    expect(await screen.findByRole("cell", { name: "B-current" })).toBeInTheDocument();
    view.rerender(board({ ...props, endpoint: "/a", title: "A again" }));
    expect(await screen.findByRole("cell", { name: "A-current" })).toBeInTheDocument();

    firstA.resolve(response([{ id: 1, name: "A-old" }]));
    await waitFor(() => expect(screen.queryByRole("cell", { name: "A-old" })).not.toBeInTheDocument());
    expect(screen.getByRole("cell", { name: "A-current" })).toBeInTheDocument();
    expect(callsFor("GET", "/api/a")).toHaveLength(2);
  });

  it("[UNMOUNT-GET] aborts the active list request and sends no extra request", async () => {
    const pending = deferred<Response>();
    installFetch(async () => pending.promise);
    const view = render(board());
    await waitFor(() => expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1));
    const signal = calls[0].init?.signal as AbortSignal;
    const alert = vi.spyOn(window, "alert");
    view.unmount();
    expect(signal.aborted).toBe(true);
    pending.resolve(response([campaign]));
    await Promise.resolve();
    expect(calls).toHaveLength(1);
    expect(alert).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("[CREATE-REJECT] retains the form and shows an explicit HTTP rejection", async () => {
    installFetch(async (_url, init) =>
      methodOf(init) === "GET" ? response([campaign]) : response({ detail: "rejected" }, 400),
    );
    render(board());
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Кампания"), { target: { value: "Keep me" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Операция отклонена");
    expect(screen.getByLabelText("Кампания")).toHaveValue("Keep me");
    const save = screen.getByRole("button", { name: "Сохранить" });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(callsFor("POST", "/api/marketing/campaigns")).toHaveLength(2));
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[CREATE-NETWORK-UNKNOWN] keeps the form after a network-unknown POST without retry", async () => {
    const refresh = deferred<Response>();
    let getCount = 0;
    installFetch(async (_url, init) => {
      if (methodOf(init) === "GET") {
        getCount += 1;
        return getCount === 1 ? response([campaign]) : refresh.promise;
      }
      throw new Error("connection lost");
    });
    render(board());
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Кампания"), { target: { value: "May have saved" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Результат операции не подтверждён");
    expect(screen.getByLabelText("Кампания")).toHaveValue("May have saved");
    await waitFor(() => expect(screen.getByLabelText("Кампания")).toBeEnabled());
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
    const save = screen.getByRole("button", { name: "Сохранить" });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(callsFor("POST", "/api/marketing/campaigns")).toHaveLength(1);
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    await waitFor(() => expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(2));
    refresh.resolve(response([campaign]));
    await waitFor(() => expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled());
    expect(screen.getByRole("alert")).toHaveTextContent("Результат операции не подтверждён");
    expect(screen.getByLabelText("Кампания")).toHaveValue("May have saved");
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(callsFor("POST", "/api/marketing/campaigns")).toHaveLength(1);
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(2);
  });

  it("[CREATE-5XX-UNKNOWN] treats a server error as unknown and preserves the form", async () => {
    installFetch(async (_url, init) =>
      methodOf(init) === "GET" ? response([campaign]) : response({ detail: "failed" }, 503),
    );
    render(board());
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Кампания"), { target: { value: "Keep after 503" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503");
    expect(screen.getByLabelText("Кампания")).toHaveValue("Keep after 503");
    await waitFor(() => expect(screen.getByLabelText("Кампания")).toBeEnabled());
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
    const save = screen.getByRole("button", { name: "Сохранить" });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(callsFor("POST", "/api/marketing/campaigns")).toHaveLength(1);
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[CREATE-INVALID-2XX] preserves the form when a 2xx response is not a valid row", async () => {
    installFetch(async (_url, init) =>
      methodOf(init) === "GET" ? response([campaign]) : response({ id: 2 }, 201),
    );
    render(board());
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Кампания"), { target: { value: "Unconfirmed" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ответ не подтверждает");
    expect(screen.getByLabelText("Кампания")).toHaveValue("Unconfirmed");
    await waitFor(() => expect(screen.getByLabelText("Кампания")).toBeEnabled());
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
    const save = screen.getByRole("button", { name: "Сохранить" });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(callsFor("POST", "/api/marketing/campaigns")).toHaveLength(1);
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[WRITE-SINGLEFLIGHT] submits one POST while its confirmed response is pending", async () => {
    const pending = deferred<Response>();
    installFetch(async (_url, init) =>
      methodOf(init) === "GET" ? response([campaign]) : pending.promise,
    );
    render(board());
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Кампания"), { target: { value: "Single" } });
    const save = screen.getByRole("button", { name: "Сохранить" });
    fireEvent.click(save);
    fireEvent.click(save);
    await waitFor(() => expect(callsFor("POST", "/api/marketing/campaigns")).toHaveLength(1));
    pending.resolve(response({ ...campaign, id: 2, name: "Single" }, 201));
    await screen.findByRole("status");
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(2);
  });

  it("[CREATE-OK-REFRESH-FAIL] closes only after confirmed create and keeps stale rows on refresh failure", async () => {
    let getCount = 0;
    installFetch(async (_url, init) => {
      if (methodOf(init) === "GET") {
        getCount += 1;
        return getCount === 1 ? response([campaign]) : response({ detail: "failed" }, 503);
      }
      return response({ ...campaign, id: 2, name: "Confirmed" }, 201);
    });
    render(board());
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Кампания"), { target: { value: "Confirmed" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Операция подтверждена");
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503");
    expect(screen.queryByLabelText("Кампания")).not.toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Кампания" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
  });

  it("[STATUS-REJECT] retains the previous status after HTTP rejection", async () => {
    installFetch(async (_url, init) => methodOf(init) === "GET"
      ? response([{ ...campaign, status: "new" }])
      : response({ detail: "rejected" }, 409));
    render(board({
      columns: [{ key: "name", label: "Кампания" }, { key: "status", label: "Статус" }],
      statusKey: "status",
      statusFlow: ["new", "done"],
      patchPath: "/marketing/campaigns",
    }));
    fireEvent.click(await screen.findByRole("button", { name: "new" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Операция отклонена");
    const next = screen.getByRole("button", { name: "new" });
    expect(next).toBeEnabled();
    fireEvent.click(next);
    await waitFor(() => expect(callsFor("PATCH", "/api/marketing/campaigns/1")).toHaveLength(2));
    expect(screen.queryByRole("button", { name: "done" })).not.toBeInTheDocument();
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[STATUS-NETWORK-UNKNOWN] keeps the old status and does not refresh after network loss", async () => {
    installFetch(async (_url, init) => {
      if (methodOf(init) === "GET") return response([{ ...campaign, status: "new" }]);
      throw new Error("offline");
    });
    render(board({
      columns: [{ key: "name", label: "Кампания" }, { key: "status", label: "Статус" }],
      statusKey: "status",
      statusFlow: ["new", "done"],
      patchPath: "/marketing/campaigns",
    }));
    fireEvent.click(await screen.findByRole("button", { name: "new" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Результат операции не подтверждён");
    await waitFor(() => expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled());
    const status = screen.getByRole("button", { name: "new" });
    expect(status).toBeDisabled();
    fireEvent.click(status);
    expect(callsFor("PATCH", "/api/marketing/campaigns/1")).toHaveLength(1);
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[STATUS-INVALID-2XX] rejects a success response for a different row or status", async () => {
    installFetch(async (_url, init) => methodOf(init) === "GET"
      ? response([{ ...campaign, status: "new" }])
      : response({ ...campaign, id: 9, status: "done" }));
    render(board({
      columns: [{ key: "name", label: "Кампания" }, { key: "status", label: "Статус" }],
      statusKey: "status",
      statusFlow: ["new", "done"],
      patchPath: "/marketing/campaigns",
    }));
    fireEvent.click(await screen.findByRole("button", { name: "new" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ответ не подтверждает");
    await waitFor(() => expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled());
    const status = screen.getByRole("button", { name: "new" });
    expect(status).toBeDisabled();
    fireEvent.click(status);
    expect(callsFor("PATCH", "/api/marketing/campaigns/1")).toHaveLength(1);
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[STATUS-UNKNOWN-FLOW] denies an unknown current status instead of wrapping it", async () => {
    installFetch(async () => response([{ ...campaign, status: "mystery" }]));
    render(board({
      columns: [{ key: "name", label: "Кампания" }, { key: "status", label: "Статус" }],
      statusKey: "status",
      statusFlow: ["new", "done"],
      patchPath: "/marketing/campaigns",
    }));
    const status = await screen.findByRole("button", { name: "mystery" });
    expect(status).toBeDisabled();
    fireEvent.click(status);
    expect(callsFor("PATCH")).toHaveLength(0);
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[ACTION-REJECT] reports action rejection and preserves the numeric form value", async () => {
    installFetch(async (_url, init) => methodOf(init) === "GET"
      ? response([campaign])
      : response({ detail: "rejected" }, 409));
    render(board({
      fields: [...campaignFields, { key: "target", label: "Цель числом", type: "number", default: 0 }],
      action: { label: "Запустить", path: "/marketing/campaigns/{id}/launch" },
    }));
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Цель числом"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Операция отклонена");
    expect(screen.getByLabelText("Цель числом")).toHaveValue(5);
    const launch = screen.getByRole("button", { name: "Запустить" });
    expect(launch).toBeEnabled();
    fireEvent.click(launch);
    await waitFor(() => expect(callsFor("POST", "/api/marketing/campaigns/1/launch")).toHaveLength(2));
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[ACTION-NETWORK-UNKNOWN] keeps the numeric form and does not retry after network loss", async () => {
    installFetch(async (_url, init) => {
      if (methodOf(init) === "GET") return response([campaign]);
      throw new Error("offline");
    });
    render(board({
      fields: [...campaignFields, { key: "target", label: "Цель числом", type: "number", default: 0 }],
      action: { label: "Запустить", path: "/marketing/campaigns/{id}/launch" },
    }));
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Цель числом"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Результат операции не подтверждён");
    expect(screen.getByLabelText("Цель числом")).toHaveValue(5);
    await waitFor(() => expect(screen.getByLabelText("Цель числом")).toBeEnabled());
    const launch = screen.getByRole("button", { name: "Запустить" });
    expect(launch).toBeDisabled();
    fireEvent.click(launch);
    expect(callsFor("POST", "/api/marketing/campaigns/1/launch")).toHaveLength(1);
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[ACTION-INVALID-2XX] does not accept an action response for another row", async () => {
    installFetch(async (_url, init) => methodOf(init) === "GET"
      ? response([campaign])
      : response({ ...campaign, id: 9 }));
    render(board({ action: { label: "Запустить", path: "/marketing/campaigns/{id}/launch" } }));
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ответ не подтверждает");
    await waitFor(() => expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "Запустить" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
    expect(callsFor("POST", "/api/marketing/campaigns/1/launch")).toHaveLength(1);
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[ENDPOINT-WRITE-LATE] ignores an old A write after A → B → A without clearing new form or refreshing", async () => {
    const pendingPost = deferred<Response>();
    let aGets = 0;
    installFetch(async (url, init) => {
      if (methodOf(init) === "GET") {
        if (url === "/api/a") {
          aGets += 1;
          return response([{ id: 1, name: aGets === 1 ? "A-before" : "A-current" }]);
        }
        return response([{ id: 2, name: "B-current" }]);
      }
      return pendingPost.promise;
    });
    const props = {
      ...baseProps,
      columns: [{ key: "name", label: "Имя" }],
      fields: [{ key: "name", label: "Имя" }],
    };
    const view = render(board({ ...props, endpoint: "/a", title: "A" }));
    expect(await screen.findByRole("cell", { name: "A-before" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "old A command" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(callsFor("POST", "/api/a")).toHaveLength(1));

    view.rerender(board({ ...props, endpoint: "/b", title: "B" }));
    expect(await screen.findByRole("cell", { name: "B-current" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "B draft" } });

    view.rerender(board({ ...props, endpoint: "/a", title: "A again" }));
    expect(await screen.findByRole("cell", { name: "A-current" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "new A draft" } });
    const getCountBeforeLateWrite = callsFor("GET", "/api/a").length;

    pendingPost.resolve(response({ id: 3, name: "old A command" }, 201));
    await waitFor(() => expect(screen.getByLabelText("Имя")).toHaveValue("new A draft"));
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeInTheDocument();
    expect(callsFor("GET", "/api/a")).toHaveLength(getCountBeforeLateWrite);
    expect(callsFor("POST", "/api/a")).toHaveLength(1);
    expect(screen.queryByText("Операция подтверждена; список обновлён.")).not.toBeInTheDocument();
  });

  it("[UNMOUNT-WRITE] ignores a late confirmed POST after unmount without adding a GET", async () => {
    const pendingPost = deferred<Response>();
    installFetch(async (_url, init) =>
      methodOf(init) === "GET" ? response([campaign]) : pendingPost.promise,
    );
    const view = render(board());
    await screen.findByRole("cell", { name: "Кампания" });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(callsFor("POST", "/api/marketing/campaigns")).toHaveLength(1));
    const alert = vi.spyOn(window, "alert");
    view.unmount();
    pendingPost.resolve(response({ ...campaign, id: 2 }, 201));
    await Promise.resolve();
    expect(callsFor("GET", "/api/marketing/campaigns")).toHaveLength(1);
    expect(alert).not.toHaveBeenCalled();
    expect(callsFor("POST", "/api/marketing/campaigns")).toHaveLength(1);
  });

  it("[SERVICE-CREATE-COMPAT] preserves the service-only create URL and request body", async () => {
    let getCount = 0;
    installFetch(async (_url, init) => {
      if (methodOf(init) === "GET") {
        getCount += 1;
        return getCount === 1
          ? response([{ id: 1, customer: "Клиент", subject: "Обращение", status: "new" }])
          : response([{ id: 2, customer: "ООО Клиент", subject: "Проверка доставки", status: "new" }]);
      }
      return response({ id: 2, customer: "ООО Клиент", subject: "Проверка доставки", status: "new" }, 201);
    });
    render(board({
      title: "Сервис",
      endpoint: "/service/tickets",
      columns: [
        { key: "customer", label: "Клиент" },
        { key: "subject", label: "Тема" },
        { key: "status", label: "Статус" },
      ],
      fields: [
        { key: "customer", label: "Клиент" },
        { key: "subject", label: "Тема" },
      ],
    }));
    expect(await screen.findByRole("cell", { name: "Обращение" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    fireEvent.change(screen.getByLabelText("Клиент"), { target: { value: "ООО Клиент" } });
    fireEvent.change(screen.getByLabelText("Тема"), { target: { value: "Проверка доставки" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByRole("cell", { name: "Проверка доставки" })).toBeInTheDocument();
    const post = callsFor("POST", "/api/service/tickets");
    expect(post).toHaveLength(1);
    expect(JSON.parse(String(post[0].init?.body))).toEqual({
      customer: "ООО Клиент",
      subject: "Проверка доставки",
    });
    expect(callsFor("GET", "/api/service/tickets")).toHaveLength(2);
    expect(calls.some((call) => methodOf(call.init) === "PATCH")).toBe(false);
  });
});
