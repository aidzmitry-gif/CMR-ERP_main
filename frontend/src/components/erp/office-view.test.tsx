import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OfficeView } from "@/components/erp/office-view";
import type { Delivery } from "@/lib/office-delivery";

const board = <div>Воронка-заглушка</div>;
const heavy: Delivery = { id: 1, code: "A1", company: "ООО Тяж", weight: "400 кг", amount: 300, stage: "unknown" };
const light: Delivery = { id: 2, code: "A2", company: "ООО Лёгк", weight: "50 кг", amount: 200, stage: "unknown" };

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function officeDoc(overrides: Record<string, unknown> = {}) {
  return {
    id: 77,
    number: "LIVE-77",
    company: "ООО Живой Док",
    amount: 500,
    delivery: "",
    docs_status: "",
    stage: "shipped",
    region: "Гродно",
    weight: "120 кг",
    ...overrides,
  };
}

const carriers = [
  { id: "dellin", name: "Деловые Линии", type: "LTL", rating: 4.7, eta: "1–2 дня", price_from: 95, zone: "РБ", heavy: true },
  { id: "dpd", name: "DPD", type: "Экспресс", rating: 4.5, eta: "1–2 дня", price_from: 52, zone: "РБ", heavy: true },
];

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([], 404)));
});
afterEach(() => vi.unstubAllGlobals());

function boardWrapper() {
  return screen.getByText("Воронка-заглушка").parentElement as HTMLElement;
}
function deliveryWrapper() {
  return screen.getByRole("heading", { name: "Доставка и трекинг" }).closest("main")?.parentElement as HTMLElement;
}
function openDeliveryTab() {
  fireEvent.click(screen.getByRole("button", { name: /Доставка/ }));
}

describe("OfficeView", () => {
  it("рендерит обе вкладки и сохраняет layout доски", () => {
    render(<OfficeView board={board} initialDeliveries={[heavy, light]} />);
    expect(screen.getByRole("button", { name: /Документы/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Доставка/ })).toBeInTheDocument();
    expect(boardWrapper().className).toContain("contents");
    expect(deliveryWrapper().className).toContain("hidden");
  });

  it("не создаёт бейдж заявок из веса без подтверждённого правила", () => {
    render(<OfficeView board={board} initialDeliveries={[heavy, { ...heavy, id: 3, weight: "500 кг" }, light]} />);
    expect(screen.getByRole("button", { name: /Доставка/ }).textContent?.trim()).toBe("Доставка");
  });

  it("не выводит подтверждение заявки только из исходного текста способа доставки", () => {
    render(<OfficeView board={board} initialDeliveries={[{ ...heavy, carrier: "Деловые Линии" }]} />);
    expect(screen.getByRole("button", { name: /Доставка/ }).textContent?.trim()).toBe("Доставка");
  });

  it("клик по «Доставка» активирует секцию, а доску скрывает", () => {
    render(<OfficeView board={board} initialDeliveries={[heavy, light]} />);
    openDeliveryTab();
    expect(deliveryWrapper().className).toContain("contents");
    expect(boardWrapper().className).toContain("hidden");
  });

  it("показывает сумму документов из строк списка", () => {
    render(<OfficeView board={board} initialDeliveries={[heavy, light]} />);
    openDeliveryTab();
    expect(screen.getByText("500 BYN")).toBeInTheDocument();
    expect(screen.getByText("Сумма документов")).toBeInTheDocument();
  });

  it("не предлагает заявку для локальной строки без подтверждённой стадии ready", () => {
    render(<OfficeView board={board} initialDeliveries={[heavy]} />);
    openDeliveryTab();
    expect(screen.queryByRole("button", { name: /Заявка перевозчику/ })).not.toBeInTheDocument();
    expect(screen.getAllByText("Не указано").length).toBeGreaterThan(0);
  });

  it("сохраняет выбранный вариант и показывает отказ без оптимистического назначения", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/office/docs") return jsonResponse([officeDoc({ stage: "ready", weight: "600 кг" })]);
      if (url === "/api/office/carriers") return jsonResponse(carriers);
      if (url.endsWith("/carrier-request")) return jsonResponse({ detail: "invalid request" }, 422);
      return jsonResponse([], 404);
    }));
    render(<OfficeView board={board} />);
    openDeliveryTab();
    await screen.findByText("LIVE-77");
    fireEvent.click(screen.getByRole("button", { name: /Заявка перевозчику/ }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "dpd" } });
    fireEvent.click(screen.getByRole("button", { name: /Отправить заявку/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 422");
    expect(screen.getByRole("combobox")).toHaveValue("dpd");
    const row = screen.getByText("LIVE-77").closest("tr");
    expect(row).not.toHaveTextContent("DPD");
    expect(screen.getByRole("button", { name: /Отправить заявку/ })).toBeInTheDocument();
  });

  it("успешный список документов заменяет ранее показанные строки", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/office/docs") return jsonResponse([officeDoc({ docs_status: "Доставка: В пути" })]);
      return jsonResponse([], 404);
    }));
    render(<OfficeView board={board} initialDeliveries={[heavy, light]} />);
    openDeliveryTab();
    expect(await screen.findByText("ООО Живой Док")).toBeInTheDocument();
    expect(screen.queryByText("ООО Тяж")).not.toBeInTheDocument();
    expect(screen.getByText("Статус подтверждён для 1 из 1 документов; вес указан для 1 из 1.")).toBeInTheDocument();
  });

  it("POST сохраняет прежнее тело и отказ не превращает его в успешное назначение", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/api/office/docs") return jsonResponse([officeDoc({ id: 88, number: "LIVE-88", stage: "ready", region: "Минск" })]);
      if (url === "/api/office/carriers") return jsonResponse(carriers);
      if (url === "/api/office/docs/88/carrier-request") return jsonResponse({ detail: "invalid request" }, 422);
      return jsonResponse([], 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<OfficeView board={board} />);
    openDeliveryTab();
    await screen.findByText("LIVE-88");
    fireEvent.click(screen.getByRole("button", { name: /Заявка перевозчику/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Отправить заявку/ }));
    await screen.findByRole("alert");
    const post = fetchMock.mock.calls.find(([url]) => url === "/api/office/docs/88/carrier-request");
    expect((post?.[1] as RequestInit)?.method).toBe("POST");
    expect(JSON.parse((post?.[1] as RequestInit)?.body as string)).toEqual({ carrier: "dellin", region: "Минск" });
    expect(screen.getByRole("button", { name: /Отправить заявку/ })).toBeInTheDocument();
    expect(screen.getByText("Не подтверждён")).toBeInTheDocument();
  });

  it("INITIAL-LOADING-NO-DEMO: до ответа показывает загрузку, а не демо-строки", async () => {
    let resolveDocs!: (value: Response) => void;
    const fetchMock = vi.fn((url: string) => url === "/api/office/docs"
      ? new Promise<Response>((resolve) => { resolveDocs = resolve; })
      : new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    render(<OfficeView board={board} />);
    openDeliveryTab();
    expect(screen.getByText("Загружаем документы…")).toBeInTheDocument();
    expect(screen.queryByText("ООО МеталлПром")).not.toBeInTheDocument();
    expect(screen.queryByText("Документов нет")).not.toBeInTheDocument();
    await act(async () => resolveDocs(jsonResponse([])));
  });

  it("REAL-EMPTY: успешный пустой ответ виден как пустой список, не как ошибка", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([], 200)));
    render(<OfficeView board={board} />);
    openDeliveryTab();
    expect(await screen.findByText("Документов нет")).toBeInTheDocument();
    expect(screen.getByText("Документов").parentElement).toHaveTextContent("0");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("HTTP-ERROR-RETRY: сообщает HTTP-ошибку и повторяет загрузку текущего списка", async () => {
    let docsCalls = 0;
    let resolveRetry!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url !== "/api/office/docs") return jsonResponse([], 200);
      docsCalls += 1;
      return docsCalls === 1
        ? jsonResponse({ detail: "unauthorized" }, 503)
        : new Promise<Response>((resolve) => { resolveRetry = resolve; });
    }));
    render(<OfficeView board={board} />);
    openDeliveryTab();
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503");
    expect(screen.queryByText("Документов нет")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Загружаем документы…")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Документов нет")).not.toBeInTheDocument();
    await act(async () => resolveRetry(jsonResponse([officeDoc()])));
    expect(await screen.findByText("LIVE-77")).toBeInTheDocument();
    expect(docsCalls).toBe(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("NETWORK-ERROR: distinguishes a network failure from a valid empty response", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/office/docs") throw new TypeError("Failed to fetch");
      return jsonResponse([], 200);
    }));
    render(<OfficeView board={board} />);
    openDeliveryTab();
    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to fetch");
    expect(screen.queryByText("Документов нет")).not.toBeInTheDocument();
  });

  it("MALFORMED-DOCS: rejects a non-list JSON response instead of rendering zero", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => jsonResponse(url === "/api/office/docs" ? { docs: [] } : [], 200)));
    render(<OfficeView board={board} />);
    openDeliveryTab();
    expect(await screen.findByRole("alert")).toHaveTextContent("некорректный список документов");
    expect(screen.queryByText("Документов нет")).not.toBeInTheDocument();
    expect(screen.queryByText("Документов")).not.toBeInTheDocument();
  });

  it("STALE-ROWS-NOT-CURRENT: сохраняет предыдущие строки как устаревшие при неудаче повтора", async () => {
    let docsCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url !== "/api/office/docs") return jsonResponse([], 200);
      docsCalls += 1;
      return docsCalls === 1 ? jsonResponse([officeDoc()]) : jsonResponse([], 500);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<OfficeView board={board} />);
    openDeliveryTab();
    expect(await screen.findByText("LIVE-77")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Обновить документы" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 500");
    expect(screen.getByText("Показаны сохранённые строки; текущий список ещё не подтверждён.")).toBeInTheDocument();
    expect(screen.getByText("LIVE-77")).toBeInTheDocument();
  });

  it("UNMOUNT-ABORT: отменяет обе GET-заявки и игнорирует поздний ответ после unmount", async () => {
    const pending: Array<(response: Response) => void> = [];
    const fetchMock = vi.fn<typeof fetch>(() => new Promise<Response>((resolve) => pending.push(resolve)));
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = render(<OfficeView board={board} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const signals = fetchMock.mock.calls.map(([, options]) => (options as RequestInit).signal);
    unmount();
    expect(signals).toHaveLength(2);
    expect(signals.every((signal) => signal?.aborted)).toBe(true);
    await act(async () => {
      for (const resolve of pending) resolve(jsonResponse([officeDoc()]));
      await Promise.resolve();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("CARRIERS-FAIL-NO-PROTOTYPE: каталог API ошибку показывает отдельно и не подменяет статическим списком", async () => {
    let carrierCalls = 0;
    let resolveRetry!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/office/docs") return jsonResponse([]);
      carrierCalls += 1;
      return carrierCalls === 1
        ? jsonResponse([], 503)
        : new Promise<Response>((resolve) => { resolveRetry = resolve; });
    }));
    render(<OfficeView board={board} />);
    openDeliveryTab();
    expect(await screen.findByText(/Справочник вариантов: сервер вернул HTTP 503/)).toBeInTheDocument();
    expect(screen.queryByText("Деловые Линии")).not.toBeInTheDocument();
    expect(screen.queryByText("СДЭК")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить справочник" }));
    expect(await screen.findByText("Загружаем справочник вариантов…")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Деловые Линии")).not.toBeInTheDocument();
    await act(async () => resolveRetry(jsonResponse([])));
    expect(carrierCalls).toBe(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Деловые Линии")).not.toBeInTheDocument();
    expect(screen.queryByText("СДЭК")).not.toBeInTheDocument();
  });

  it("POST-FAIL-FORM-PRESERVED: сохраняет введённые поля и не закрывает форму после отказа", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/office/docs") return jsonResponse([officeDoc({ id: 88, number: "LIVE-88", stage: "ready" })]);
      if (url === "/api/office/carriers") return jsonResponse(carriers);
      return jsonResponse({ detail: "invalid request" }, 422);
    }));
    render(<OfficeView board={board} />);
    openDeliveryTab();
    await screen.findByText("LIVE-88");
    fireEvent.click(screen.getByRole("button", { name: /Заявка перевозчику/ }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "dpd" } });
    fireEvent.change(screen.getByPlaceholderText("напр. 12.06"), { target: { value: "20.10" } });
    fireEvent.change(screen.getByPlaceholderText("Адрес, контактное лицо, упаковка…"), { target: { value: "Въезд со двора" } });
    fireEvent.click(screen.getByRole("button", { name: /Отправить заявку/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 422");
    expect(screen.getByRole("combobox")).toHaveValue("dpd");
    expect(screen.getByPlaceholderText("напр. 12.06")).toHaveValue("20.10");
    expect(screen.getByPlaceholderText("Адрес, контактное лицо, упаковка…")).toHaveValue("Въезд со двора");
    expect(screen.getByRole("button", { name: /Отправить заявку/ })).toBeInTheDocument();
    expect(screen.getByText("LIVE-88").closest("tr")).not.toHaveTextContent("DPD");
  });

  it("UNKNOWN-FACTS-COVERAGE: не выводит оплату как доставку, op_date как ETA и пустой вес как 0 кг", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url !== "/api/office/docs") return jsonResponse([]);
      return jsonResponse([
        officeDoc({ id: 1, number: "PAID-1", company: "ООО Оплачено", stage: "paid", docs_status: "Оплачено", weight: "", op_date: "2026-10-01" }),
        officeDoc({ id: 2, number: "SHIP-2", company: "ООО В пути", stage: "shipped", docs_status: "Доставка: В пути", weight: "500 кг", op_date: "2026-10-02" }),
      ]);
    }));
    render(<OfficeView board={board} />);
    openDeliveryTab();
    expect(await screen.findByText("PAID-1")).toBeInTheDocument();
    expect(screen.getByText("Статус подтверждён для 1 из 2 документов; вес указан для 1 из 2.")).toBeInTheDocument();
    const paidRow = screen.getByText("PAID-1").closest("tr");
    expect(paidRow).toHaveTextContent("Не подтверждён");
    expect(paidRow).toHaveTextContent("Не указан");
    expect(paidRow).not.toHaveTextContent("Доставлена");
    expect(screen.queryByText("2026-10-01")).not.toBeInTheDocument();
    expect(screen.queryByText("2026-10-02")).not.toBeInTheDocument();
  });

  it("CARRIERS-PROTOTYPE-RESPONSE-NO-COMMERCIAL-CLAIMS: успешный прототип показывает только имена и предупреждение", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/office/docs") return jsonResponse([officeDoc({ stage: "ready" })]);
      if (url === "/api/office/carriers") return jsonResponse(carriers);
      return jsonResponse([], 404);
    }));
    render(<OfficeView board={board} />);
    openDeliveryTab();
    await screen.findByText("LIVE-77");
    expect(await screen.findByText(/Справочник вариантов прототипный/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Заявка перевозчику/ }));
    expect(screen.getByRole("combobox")).toHaveTextContent("Деловые Линии");
    expect(screen.getByText("Варианты из прототипного справочника. Тарифы, сроки, рейтинг и пригодность не подтверждены.")).toBeInTheDocument();
    const visible = document.body.textContent ?? "";
    expect(visible).not.toContain("95 BYN");
    expect(visible).not.toContain("4.7");
    expect(visible).not.toContain("1–2 дня");
    expect(visible).not.toContain("тяжёлые");
  });

  it("UNVERIFIED-2XX-FORM-PRESERVED: непроверенный 2xx не подтверждает назначение и сохраняет форму", async () => {
    let docsCalls = 0;
    let carrierCalls = 0;
    let postCalls = 0;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/office/docs") {
        docsCalls += 1;
        return jsonResponse([officeDoc({ id: 89, number: "LIVE-89", stage: "ready", region: "Минск" })]);
      }
      if (url === "/api/office/carriers") {
        carrierCalls += 1;
        return jsonResponse(carriers);
      }
      if (url === "/api/office/docs/89/carrier-request" && init?.method === "POST") {
        postCalls += 1;
        return jsonResponse({ request_id: "prototype-accepted" }, 200);
      }
      return jsonResponse([], 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<OfficeView board={board} />);
    openDeliveryTab();
    await screen.findByText("LIVE-89");
    fireEvent.click(screen.getByRole("button", { name: /Заявка перевозчику/ }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "dpd" } });
    fireEvent.change(screen.getByPlaceholderText("напр. 12.06"), { target: { value: "20.10" } });
    fireEvent.change(screen.getByPlaceholderText("Адрес, контактное лицо, упаковка…"), { target: { value: "Въезд со двора" } });
    fireEvent.click(screen.getByRole("button", { name: /Отправить заявку/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("не подтверждает назначение перевозчика");
    expect(screen.getByRole("combobox")).toHaveValue("dpd");
    expect(screen.getByPlaceholderText("напр. 12.06")).toHaveValue("20.10");
    expect(screen.getByPlaceholderText("Адрес, контактное лицо, упаковка…")).toHaveValue("Въезд со двора");
    expect(screen.getByRole("button", { name: /Отправить заявку/ })).toBeInTheDocument();
    const row = screen.getByText("LIVE-89").closest("tr");
    expect(row).toHaveTextContent("Заявка перевозчику");
    expect(row).not.toHaveTextContent("DPD");
    expect(docsCalls).toBe(1);
    expect(carrierCalls).toBe(1);
    expect(postCalls).toBe(1);
    const post = fetchMock.mock.calls.find(([url]) => url === "/api/office/docs/89/carrier-request");
    expect(JSON.parse((post?.[1] as RequestInit)?.body as string)).toEqual({ carrier: "dpd", region: "Минск" });
  });
});
