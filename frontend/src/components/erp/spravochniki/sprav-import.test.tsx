import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SpravImport } from "@/components/erp/spravochniki/sprav-import";

// Компонент дёргает глобальный fetch("/api/integrations/1c/sync", POST).
// Мокаем ТОЛЬКО сеть — formatSyncSummary/lucide рендерим по-настоящему.
const fetchMock = vi.fn();

function okResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}

afterEach(() => {
  vi.restoreAllMocks();
  fetchMock.mockReset();
});

function stubFetch() {
  vi.stubGlobal("fetch", fetchMock);
}

describe("SpravImport — LIVE-синхронизация с 1С", () => {
  it("до синка: показывает подсказку и не показывает итоги/ошибку", () => {
    stubFetch();
    render(<SpravImport />);

    expect(
      screen.getByRole("heading", { name: "Импорт из 1С — контрагенты" }),
    ).toBeInTheDocument();
    // пустая ветка: приглашение нажать «Синхронизировать»
    expect(
      screen.getByText(/Нажмите «Синхронизировать», чтобы запустить синк/),
    ).toBeInTheDocument();
    // ни итогов, ни ошибки, fetch не дёргался на маунте
    expect(screen.queryByText("Контрагентов обработано")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("успешный синк: POST на нужный эндпоинт и рендер всех 4 плиток с числами", async () => {
    stubFetch();
    fetchMock.mockResolvedValue(
      okResponse({
        counterparties: 218,
        new_counterparties: 140,
        counterparty_aliases: 42,
        stock: 507,
      }),
    );
    render(<SpravImport />);

    fireEvent.click(screen.getByRole("button", { name: "Синхронизировать" }));

    expect(await screen.findByText("Контрагентов обработано")).toBeInTheDocument();
    // числа из ответа проброшены в плитки (значения < 1000 — без ru-RU разделителей)
    expect(screen.getByText("218")).toBeInTheDocument();
    expect(screen.getByText("140")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("507")).toBeInTheDocument();
    expect(screen.getByText("Позиций склада")).toBeInTheDocument();

    // ушёл POST на правильный URL, подсказка исчезла
    expect(fetchMock).toHaveBeenCalledWith("/api/integrations/1c/sync", { method: "POST" });
    expect(
      screen.queryByText(/Нажмите «Синхронизировать», чтобы запустить синк/),
    ).not.toBeInTheDocument();
  });

  it("во время синка: кнопка блокируется и меняет текст на «Синхронизируется…»", async () => {
    stubFetch();
    // управляемый промис — держим fetch в pending, ловим состояние загрузки
    let resolveFetch: (r: Response) => void = () => {};
    fetchMock.mockReturnValue(new Promise<Response>((r) => (resolveFetch = r)));
    render(<SpravImport />);

    const btn = screen.getByRole("button", { name: "Синхронизировать" });
    fireEvent.click(btn);

    // синхронно после клика: state syncing=true
    const loadingBtn = await screen.findByRole("button", { name: "Синхронизируется…" });
    expect(loadingBtn).toBeDisabled();

    // завершаем — возвращается в обычное состояние
    resolveFetch(okResponse({ counterparties: 1, new_counterparties: 0, counterparty_aliases: 0, stock: 0 }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Синхронизировать" })).toBeEnabled(),
    );
  });

  it("HTTP-ошибка: показывает «HTTP 500», без плиток итогов", async () => {
    stubFetch();
    fetchMock.mockResolvedValue({ ok: false, status: 500 } as unknown as Response);
    render(<SpravImport />);

    fireEvent.click(screen.getByRole("button", { name: "Синхронизировать" }));

    expect(await screen.findByText("HTTP 500")).toBeInTheDocument();
    expect(screen.queryByText("Контрагентов обработано")).not.toBeInTheDocument();
    // подсказка тоже скрывается (есть ошибка)
    expect(
      screen.queryByText(/Нажмите «Синхронизировать», чтобы запустить синк/),
    ).not.toBeInTheDocument();
  });

  it("сетевой сбой: сообщение ошибки из исключения, кнопка снова активна", async () => {
    stubFetch();
    fetchMock.mockRejectedValue(new Error("Network down"));
    render(<SpravImport />);

    fireEvent.click(screen.getByRole("button", { name: "Синхронизировать" }));

    expect(await screen.findByText("Network down")).toBeInTheDocument();
    // finally-ветка вернула кнопку в рабочее состояние
    expect(screen.getByRole("button", { name: "Синхронизировать" })).toBeEnabled();
  });

  it("повторный синк после ошибки очищает ошибку и показывает итоги", async () => {
    stubFetch();
    fetchMock.mockRejectedValueOnce(new Error("Network down"));
    render(<SpravImport />);

    fireEvent.click(screen.getByRole("button", { name: "Синхронизировать" }));
    expect(await screen.findByText("Network down")).toBeInTheDocument();

    // второй прогон — успех: ошибка должна уйти (setSyncError(null) в начале handleSync)
    fetchMock.mockResolvedValueOnce(
      okResponse({ counterparties: 5, new_counterparties: 2, counterparty_aliases: 1, stock: 3 }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Синхронизировать" }));

    expect(await screen.findByText("Контрагентов обработано")).toBeInTheDocument();
    expect(screen.queryByText("Network down")).not.toBeInTheDocument();
  });
});

describe("SpravImport — ДЕМО предпросмотр и конфликты", () => {
  it("рендерит строки предпросмотра с бейджами действий из ACTION_BADGE", () => {
    stubFetch();
    render(<SpravImport />);

    // конкретные демо-строки и их action-бейджи (проверка маппинга action → label)
    expect(screen.getByText("ООО «Аккум-Сервис»")).toBeInTheDocument();
    expect(screen.getByText("ООО «Прогресс-Бат»")).toBeInTheDocument();
    // conflict-строка → бейдж «Конфликт»
    expect(screen.getByText("Конфликт")).toBeInTheDocument();
    // merge-строка → бейдж «Дубль → merge»
    expect(screen.getByText("Дубль → merge")).toBeInTheDocument();
    // сводка конфликтов в шапке шага 3
    expect(screen.getByText("Конфликтов 2")).toBeInTheDocument();
  });

  it("ключевая строка маппинга УНП несёт бейдж ключа сопоставления", () => {
    stubFetch();
    render(<SpravImport />);
    expect(screen.getByText("🔑 ключ сопоставления")).toBeInTheDocument();
    // demo-кнопка импорта неактивна (бэкенда шага нет)
    expect(screen.getByRole("button", { name: "Импортировать 216" })).toBeDisabled();
  });
});
