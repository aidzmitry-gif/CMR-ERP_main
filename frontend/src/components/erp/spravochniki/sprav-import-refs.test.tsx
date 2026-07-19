import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО сетевой bulkUpsertRef; parseRefCsv — чистый хелпер, оставляем настоящим
// (компонент реально считает строки через него — это часть проверяемого поведения).
vi.mock("@/lib/reference-data", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/reference-data")>();
  return { ...actual, bulkUpsertRef: vi.fn() };
});

import { SpravImportRefs } from "@/components/erp/spravochniki/sprav-import-refs";
import { bulkUpsertRef, type BulkApplied, type BulkPlan } from "@/lib/reference-data";

const mockBulk = bulkUpsertRef as unknown as ReturnType<typeof vi.fn>;

function plan(over: Partial<BulkPlan> = {}): BulkPlan {
  return {
    dry_run: true,
    would_create: [{ key: "USD" }],
    would_update: [],
    conflicts: [],
    ...over,
  };
}
function applied(over: Partial<BulkApplied> = {}): BulkApplied {
  return { created: 0, updated: 0, conflicts: [], ...over };
}

const preview = () => screen.getByRole("button", { name: /Предпросмотр/ });
const apply = () => screen.getByRole("button", { name: /Применить|Применение/ });
const textarea = () => document.querySelector("textarea") as HTMLTextAreaElement;

beforeEach(() => vi.clearAllMocks());

describe("SpravImportRefs", () => {
  it("считает распознанные строки из вставленного CSV и включает предпросмотр", () => {
    render(<SpravImportRefs />);
    // Пусто → 0 строк, кнопка предпросмотра выключена
    expect(screen.getByText(/Распознано строк: 0/)).toBeInTheDocument();
    expect(preview()).toBeDisabled();

    fireEvent.change(textarea(), { target: { value: "USD,Доллар\nEUR,Евро" } });

    expect(screen.getByText(/Распознано строк: 2/)).toBeInTheDocument();
    expect(preview()).toBeEnabled();
  });

  it("отбрасывает строку-заголовок при подсчёте (parseRefCsv в деле)", () => {
    render(<SpravImportRefs />);
    // первая ячейка == cols[0] ("code") → это заголовок, в счёт не идёт
    fireEvent.change(textarea(), { target: { value: "code,title\nUSD,Доллар" } });
    expect(screen.getByText(/Распознано строк: 1/)).toBeInTheDocument();
  });

  it("предпросмотр зовёт bulkUpsertRef с таблицей по умолчанию, разобранными строками и dry_run=true", async () => {
    mockBulk.mockResolvedValue(plan());
    render(<SpravImportRefs />);
    fireEvent.change(textarea(), { target: { value: "USD,Доллар\nEUR,Евро" } });

    fireEvent.click(preview());

    // таблица по умолчанию — units (первый в списке); строки — из parseRefCsv; режим — dry-run
    await waitFor(() =>
      expect(mockBulk).toHaveBeenCalledWith(
        "units",
        [
          { code: "USD", title: "Доллар" },
          { code: "EUR", title: "Евро" },
        ],
        true,
      ),
    );
  });

  it("план (dry-run) показывает счётчики создать/обновить/конфликты", async () => {
    mockBulk.mockResolvedValue(
      plan({
        would_create: [{ key: "USD" }, { key: "EUR" }],
        would_update: [{ key: "BYN", changes: { title: "Рубль", swift: "X" } }],
        conflicts: [],
      }),
    );
    render(<SpravImportRefs />);
    fireEvent.change(textarea(), { target: { value: "USD,Доллар\nEUR,Евро\nBYN,Рубль" } });
    fireEvent.click(preview());

    expect(await screen.findByText(/создать 2/)).toBeInTheDocument();
    expect(screen.getByText(/обновить 1/)).toBeInTheDocument();
    expect(screen.getByText(/конфликтов 0/)).toBeInTheDocument();
    // строка обновления перечисляет ключ и изменённые поля
    expect(screen.getAllByText(/BYN/).length).toBeGreaterThan(0);
    expect(screen.getByText(/title, swift/)).toBeInTheDocument();
  });

  it("конфликтные строки показаны явно ПЕРЕД записью, с причиной", async () => {
    mockBulk.mockResolvedValue(
      plan({
        would_create: [],
        conflicts: [{ key: "USD", reason: "дубль кода в импорте" }],
      }),
    );
    render(<SpravImportRefs />);
    fireEvent.change(textarea(), { target: { value: "USD,Доллар" } });
    fireEvent.click(preview());

    expect(await screen.findByText(/конфликтов 1/)).toBeInTheDocument();
    expect(screen.getByText(/Конфликтные строки в импорт не попадут/)).toBeInTheDocument();
    expect(screen.getByText(/дубль кода в импорте/)).toBeInTheDocument();
  });

  it("«Применить» заблокировано без предпросмотра и разблокируется после плана", async () => {
    mockBulk.mockResolvedValue(plan());
    render(<SpravImportRefs />);
    fireEvent.change(textarea(), { target: { value: "USD,Доллар" } });

    expect(apply()).toBeDisabled(); // нет плана — нельзя писать
    fireEvent.click(preview());
    await screen.findByText(/создать 1/);
    expect(apply()).toBeEnabled();
  });

  it("применение зовёт bulkUpsertRef(dry_run=false) и показывает итог записи", async () => {
    mockBulk.mockResolvedValueOnce(plan()); // предпросмотр
    render(<SpravImportRefs />);
    fireEvent.change(textarea(), { target: { value: "USD,Доллар\nEUR,Евро" } });
    fireEvent.click(preview());
    await screen.findByText(/создать 1/);

    mockBulk.mockResolvedValueOnce(applied({ created: 2, updated: 1, conflicts: [] }));
    fireEvent.click(apply());

    const ok = await screen.findByText(/Импортировано/);
    expect(ok).toHaveTextContent("создано 2, обновлено 1");
    // последний вызов — реальная запись (dry_run=false)
    const lastCall = mockBulk.mock.calls[mockBulk.mock.calls.length - 1];
    expect(lastCall[2]).toBe(false);
  });

  it("итог записи с конфликтами дописывает «пропущено конфликтов N»", async () => {
    mockBulk.mockResolvedValueOnce(plan({ conflicts: [{ key: "USD", reason: "x" }] }));
    render(<SpravImportRefs />);
    fireEvent.change(textarea(), { target: { value: "USD,Доллар" } });
    fireEvent.click(preview());
    await screen.findByText(/создать 1/);

    mockBulk.mockResolvedValueOnce(applied({ created: 1, updated: 0, conflicts: [{ key: "EUR", reason: "y" }] }));
    fireEvent.click(apply());

    const ok = await screen.findByText(/Импортировано/);
    expect(ok).toHaveTextContent("пропущено конфликтов 1");
  });

  it("ошибка запроса (bulkUpsertRef → null) показывает сообщение, а не молчит", async () => {
    mockBulk.mockResolvedValue(null);
    render(<SpravImportRefs />);
    fireEvent.change(textarea(), { target: { value: "USD,Доллар" } });
    fireEvent.click(preview());

    expect(await screen.findByText(/Ошибка запроса/)).toBeInTheDocument();
    // плана нет → «Применить» осталось заблокированным
    expect(apply()).toBeDisabled();
  });

  it("смена справочника сбрасывает план и меняет подсказку колонок", async () => {
    mockBulk.mockResolvedValue(plan());
    render(<SpravImportRefs />);
    fireEvent.change(textarea(), { target: { value: "USD,Доллар" } });
    fireEvent.click(preview());
    await screen.findByText(/создать 1/);

    // Банки → колонки code · title · swift; план исчезает (reset)
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "banks" } });
    expect(screen.getByText(/code · title · swift/)).toBeInTheDocument();
    expect(screen.queryByText(/создать 1/)).not.toBeInTheDocument();
    expect(apply()).toBeDisabled();
  });

  it("правка текста после плана сбрасывает план (нельзя писать несверенное)", async () => {
    mockBulk.mockResolvedValue(plan());
    render(<SpravImportRefs />);
    fireEvent.change(textarea(), { target: { value: "USD,Доллар" } });
    fireEvent.click(preview());
    await screen.findByText(/создать 1/);
    expect(apply()).toBeEnabled();

    fireEvent.change(textarea(), { target: { value: "USD,Доллар\nEUR,Евро" } });
    expect(screen.queryByText(/создать 1/)).not.toBeInTheDocument();
    expect(apply()).toBeDisabled(); // план устарел — снова нужен предпросмотр
  });
});
