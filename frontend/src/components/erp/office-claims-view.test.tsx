import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OfficeClaimsView } from "@/components/erp/office-claims-view";

// Компонент ходит в бэкенд напрямую через глобальный fetch (не через @/lib/api):
// GET /api/office/claims?<фильтры> и POST /api/office/claims. Мокаем сам fetch.
type Claim = {
  id: number;
  number: string;
  counterparty_name: string;
  claim_type: string;
  status: string;
  filed_at: string | null;
  amount_byn: string;
  description: string;
};

const SAMPLE: Claim = {
  id: 1,
  number: "ПРЕТ-2026-0001",
  counterparty_name: "ООО Поставщик Икс",
  claim_type: "overdue_payment",
  status: "open",
  filed_at: "2026-07-10",
  amount_byn: "1500.00",
  description: "Просрочка на 30 дней",
};

function res(ok: boolean, body: unknown, status = ok ? 200 : 500) {
  return { ok, status, json: async () => body } as Response;
}

// fetch, различающий GET-загрузку списка и POST-создание. По умолчанию POST успешен.
function installFetch(
  getBody: Claim[] = [],
  postOk = true,
  getHandler?: (url: string, opts?: RequestInit) => Promise<Response>,
  postHandler?: () => Promise<Response>,
) {
  const fetchMock = vi.fn(async (url: string, opts?: RequestInit) => {
    if (opts?.method === "POST") {
      return postHandler ? postHandler() : res(postOk, {}, postOk ? 201 : 500);
    }
    return getHandler ? getHandler(String(url), opts) : res(true, getBody);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// URL последнего GET-запроса (пропуская POST-и) — для проверки строки фильтров.
function lastGetUrl(fetchMock: ReturnType<typeof vi.fn>): string {
  for (let i = fetchMock.mock.calls.length - 1; i >= 0; i--) {
    const [url, opts] = fetchMock.mock.calls[i];
    if (!opts || opts.method !== "POST") return String(url);
  }
  return "";
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("OfficeClaimsView", () => {
  it("грузит список при монтировании и рендерит строку претензии с русскими подписями и суммой", async () => {
    installFetch([SAMPLE]);
    render(<OfficeClaimsView />);

    // данные подгрузились асинхронно из GET /api/office/claims
    const numberCell = await screen.findByText("ПРЕТ-2026-0001");
    // подписи типа/статуса дублируются в options фильтров — проверяем именно строку таблицы
    const row = within(numberCell.closest("tr") as HTMLElement);
    expect(row.getByText("ООО Поставщик Икс")).toBeInTheDocument();
    // тип overdue_payment → человекочитаемая подпись, а не код
    expect(row.getByText("Просрочка оплаты")).toBeInTheDocument();
    // статус open → бейдж «Открыта»
    expect(row.getByText("Открыта")).toBeInTheDocument();
    // сумма выводится как есть из бэкенда
    expect(row.getByText("1500.00")).toBeInTheDocument();
    expect(row.getByText("2026-07-10")).toBeInTheDocument();
  });

  it("пустой ответ показывает заглушку «Претензий нет»", async () => {
    installFetch([]);
    render(<OfficeClaimsView />);
    expect(await screen.findByText("Претензий нет")).toBeInTheDocument();
  });

  it("смена фильтра статуса перезагружает список с параметром status в URL", async () => {
    const fetchMock = installFetch([]);
    render(<OfficeClaimsView />);
    await screen.findByText("Претензий нет");

    // первый GET — без фильтров
    expect(lastGetUrl(fetchMock)).not.toContain("status=");

    // фильтр статуса — первый select на странице (форма ещё скрыта)
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[0], { target: { value: "resolved" } });

    await waitFor(() => expect(lastGetUrl(fetchMock)).toContain("status=resolved"));
  });

  it("смена фильтра типа перезагружает список с параметром claim_type", async () => {
    const fetchMock = installFetch([]);
    render(<OfficeClaimsView />);
    await screen.findByText("Претензий нет");

    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[1], { target: { value: "defect" } });

    await waitFor(() => expect(lastGetUrl(fetchMock)).toContain("claim_type=defect"));
  });

  it("кнопка «+ Претензия» раскрывает форму и переключается на «Отмена»", async () => {
    installFetch([]);
    render(<OfficeClaimsView />);
    await screen.findByText("Претензий нет");

    // форма скрыта по умолчанию
    expect(screen.queryByText("Новая претензия")).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "+ Претензия" });
    fireEvent.click(toggle);
    expect(screen.getByText("Новая претензия")).toBeInTheDocument();
    // та же кнопка теперь «Отмена» и сворачивает форму
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByText("Новая претензия")).not.toBeInTheDocument();
  });

  it("создание претензии шлёт POST с введённым контрагентом, закрывает форму и перезагружает список", async () => {
    const fetchMock = installFetch([], true);
    render(<OfficeClaimsView />);
    await screen.findByText("Претензий нет");

    fireEvent.click(screen.getByRole("button", { name: "+ Претензия" }));
    const form = screen.getByText("Новая претензия").closest("form") as HTMLElement;
    fireEvent.change(within(form).getByPlaceholderText("ООО Поставщик"), {
      target: { value: "ООО Новый Ответчик" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Создать" }));

    // ушёл POST с телом, где counterparty_name — то, что ввели
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([, o]) => o?.method === "POST");
      expect(post).toBeTruthy();
      const body = JSON.parse((post![1] as RequestInit).body as string);
      expect(body.counterparty_name).toBe("ООО Новый Ответчик");
    });
    // при успехе форма закрывается
    await waitFor(() => expect(screen.queryByText("Новая претензия")).not.toBeInTheDocument());
  });

  it("ошибка сервера при создании показывает «Ошибка 500» и оставляет форму открытой", async () => {
    installFetch([], false);
    render(<OfficeClaimsView />);
    await screen.findByText("Претензий нет");

    fireEvent.click(screen.getByRole("button", { name: "+ Претензия" }));
    const form = screen.getByText("Новая претензия").closest("form") as HTMLElement;
    fireEvent.change(within(form).getByPlaceholderText("ООО Поставщик"), {
      target: { value: "ООО Спорный" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Создать" }));

    expect(await screen.findByText("Ошибка 500")).toBeInTheDocument();
    // форма НЕ закрылась — пользователь видит, что сохранить не удалось
    expect(screen.getByText("Новая претензия")).toBeInTheDocument();
  });

  it("GET 503 показывает отдельную ошибку списка, а не успешное пустое состояние", async () => {
    installFetch([], true, async () => ({ ok: false, status: 503 } as Response));
    render(<OfficeClaimsView />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Ошибка 503");
    expect(screen.getByText("Не удалось загрузить претензии")).toBeInTheDocument();
    expect(screen.queryByText("Претензий нет")).not.toBeInTheDocument();
    expect(screen.getByText("Ошибка 503").closest("form")).toBeNull();
  });

  it("сетевая ошибка списка повторяется с текущими фильтрами и может завершиться успехом", async () => {
    let filteredCalls = 0;
    const fetchMock = installFetch([], true, async (url) => {
      if (!url.includes("claim_type=defect")) return res(true, []);
      filteredCalls += 1;
      if (filteredCalls === 1) throw new TypeError("Failed to fetch");
      return res(true, [{ ...SAMPLE, number: "ПРЕТ-RETRY" }]);
    });
    render(<OfficeClaimsView />);
    await screen.findByText("Претензий нет");
    fireEvent.change(screen.getAllByRole("combobox")[1], { target: { value: "defect" } });

    expect(await screen.findByRole("alert")).toHaveTextContent("Ошибка сети");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("ПРЕТ-RETRY")).toBeInTheDocument();
    expect(lastGetUrl(fetchMock)).toContain("claim_type=defect");
  });

  it("сбой обновления оставляет претензии тех же фильтров и явно помечает данные устаревшими", async () => {
    let calls = 0;
    installFetch([], true, async () => {
      calls += 1;
      return calls === 1 ? res(true, [SAMPLE]) : res(false, {}, 503);
    });
    render(<OfficeClaimsView />);
    expect(await screen.findByText("ПРЕТ-2026-0001")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+ Претензия" }));
    const form = screen.getByText("Новая претензия").closest("form") as HTMLElement;
    fireEvent.change(within(form).getByPlaceholderText("ООО Поставщик"), { target: { value: "ООО Обновление" } });
    fireEvent.click(within(form).getByRole("button", { name: "Создать" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Показаны ранее загруженные данные");
    expect(screen.getByText("ПРЕТ-2026-0001")).toBeInTheDocument();
    expect(screen.queryByText("Претензий нет")).not.toBeInTheDocument();
  });

  it("при смене фильтра очищает предыдущие претензии, пока загружается новый список", async () => {
    const pending = deferred<Response>();
    let calls = 0;
    installFetch([], true, () => (++calls === 1 ? res(true, [SAMPLE]) : pending.promise));
    render(<OfficeClaimsView />);
    expect(await screen.findByText("ПРЕТ-2026-0001")).toBeInTheDocument();

    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "resolved" } });
    expect(screen.queryByText("ПРЕТ-2026-0001")).not.toBeInTheDocument();
    expect(screen.getByText("Загрузка списка…")).toBeInTheDocument();
    expect(screen.queryByText("Претензий нет")).not.toBeInTheDocument();
  });

  it("поздний ответ предыдущего фильтра не перезаписывает текущий, даже если mock игнорирует abort", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    let calls = 0;
    const fetchMock = installFetch([], true, () => (++calls === 1 ? first.promise : second.promise));
    render(<OfficeClaimsView />);
    await waitFor(() => expect(fetchMock.mock.calls).toHaveLength(1));
    const firstSignal = fetchMock.mock.calls[0][1]?.signal;

    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "resolved" } });
    await waitFor(() => expect(fetchMock.mock.calls).toHaveLength(2));
    expect(firstSignal?.aborted).toBe(true);
    second.resolve(res(true, [{ ...SAMPLE, number: "ПРЕТ-CURRENT" }]));
    expect(await screen.findByText("ПРЕТ-CURRENT")).toBeInTheDocument();

    await act(async () => {
      first.resolve(res(true, [{ ...SAMPLE, number: "ПРЕТ-OLD" }]));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByText("ПРЕТ-CURRENT")).toBeInTheDocument();
    expect(screen.queryByText("ПРЕТ-OLD")).not.toBeInTheDocument();
  });

  it("размонтирование отменяет GET и поздний ответ не создаёт ошибку или новый запрос", async () => {
    const pending = deferred<Response>();
    const fetchMock = installFetch([], true, () => pending.promise);
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    const view = render(<OfficeClaimsView />);
    await waitFor(() => expect(fetchMock.mock.calls).toHaveLength(1));
    const signal = fetchMock.mock.calls[0][1]?.signal;

    view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      pending.resolve(res(false, {}, 503));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(view.container.querySelector('[role="alert"]')).toBeNull();
    expect(alertSpy).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  it("успех POST после смены фильтра перезагружает текущий фильтр, а не захваченный", async () => {
    const pendingPost = deferred<Response>();
    const fetchMock = installFetch([], true, async () => res(true, []), () => pendingPost.promise);
    render(<OfficeClaimsView />);
    await screen.findByText("Претензий нет");
    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "sent" } });
    await waitFor(() => expect(lastGetUrl(fetchMock)).toContain("status=sent"));

    fireEvent.click(screen.getByRole("button", { name: "+ Претензия" }));
    const form = screen.getByText("Новая претензия").closest("form") as HTMLElement;
    fireEvent.change(within(form).getByPlaceholderText("ООО Поставщик"), { target: { value: "ООО Тест" } });
    fireEvent.click(within(form).getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, opts]) => opts?.method === "POST")).toBe(true));

    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "resolved" } });
    await waitFor(() => expect(lastGetUrl(fetchMock)).toContain("status=resolved"));
    const beforePostComplete = fetchMock.mock.calls.length;
    pendingPost.resolve(res(true, {}, 201));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(beforePostComplete + 1));
    expect(lastGetUrl(fetchMock)).toContain("status=resolved");
    expect(lastGetUrl(fetchMock)).not.toContain("status=sent");
  });
});
