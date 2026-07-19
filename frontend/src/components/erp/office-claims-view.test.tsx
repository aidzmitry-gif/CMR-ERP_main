import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
function installFetch(getBody: Claim[] = [], postOk = true) {
  const fetchMock = vi.fn(async (_url: string, opts?: RequestInit) => {
    if (opts?.method === "POST") return res(postOk, {}, postOk ? 201 : 500);
    return res(true, getBody);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
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
});
