import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО сетевые функции модуля претензий; чистые (claimCounts/filterClaims/
// лейблы/тоны) берём из настоящей реализации — их и тестируем через рендер панели.
vi.mock("@/lib/procurement-claims", async () => {
  const actual = await vi.importActual<typeof import("@/lib/procurement-claims")>(
    "@/lib/procurement-claims",
  );
  return {
    ...actual,
    fetchClaims: vi.fn(),
    createClaim: vi.fn(),
    updateClaim: vi.fn(),
  };
});

import { ClaimsPanel } from "@/components/erp/claims-panel";
import type { Claim } from "@/lib/procurement-claims";
import * as api from "@/lib/procurement-claims";

function claim(over: Partial<Claim> = {}): Claim {
  return {
    id: 1,
    supplier: "",
    supplier_id: null,
    item: "Корпус A",
    reason: "",
    order_code: "НЗ-1",
    claim_type: "брак",
    qty_affected: 1,
    amount_byn: 1200,
    resolution: "",
    status: "open",
    source: "production",
    entity_ref: "",
    ...over,
  };
}

// Три претензии: 2 открытых (одна без поставщика) + 1 решённая.
const claims: Claim[] = [
  claim({ id: 1, item: "Корпус A", amount_byn: 1200, status: "open", supplier: "" }),
  claim({
    id: 2,
    item: "Крышка B",
    order_code: "НЗ-2",
    claim_type: "недопоставка",
    amount_byn: 500,
    status: "resolved",
    supplier: "ООО Металл",
    resolution: "компенсировано",
  }),
  claim({
    id: 3,
    item: "Вал C",
    order_code: "НЗ-3",
    claim_type: "срок",
    amount_byn: null,
    status: "open",
    supplier: "Поставщик X",
  }),
];

const mockFetch = api.fetchClaims as ReturnType<typeof vi.fn>;
const mockCreate = api.createClaim as ReturnType<typeof vi.fn>;
const mockUpdate = api.updateClaim as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  // useEffect на маунте и refresh() дёргают fetchClaims — по умолчанию отдаём тот же набор.
  mockFetch.mockResolvedValue(claims);
});

describe("ClaimsPanel", () => {
  it("рендерит KPI, строки претензий и сумму в BYN", async () => {
    render(<ClaimsPanel initial={claims} />);
    // KPI-плитки: всего 3, открыто 2, без поставщика 1, решено 1
    expect(screen.getByText("Претензий всего").closest("div")?.parentElement).toHaveTextContent("3");
    const openTile = screen.getByText("Открыто").closest("div")?.parentElement;
    expect(openTile).toHaveTextContent("2");
    expect(screen.getByText("Без поставщика").closest("div")?.parentElement).toHaveTextContent("1");
    expect(screen.getByText("Решено").closest("div")?.parentElement).toHaveTextContent("1");

    // строки таблицы
    expect(screen.getByText("Корпус A")).toBeInTheDocument();
    expect(screen.getByText("Крышка B")).toBeInTheDocument();
    // сумма 1200 форматируется ru-RU (пробел-разделитель тысяч, возможно nbsp)
    expect(screen.getByText(/1.200/)).toBeInTheDocument();
    // источник production → человекочитаемый лейбл
    expect(screen.getAllByText("Брак производства").length).toBeGreaterThan(0);
    // на маунте отработал fetchClaims (useEffect) — дожидаемся, чтобы не ловить act-warning
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
  });

  it("пустой список показывает «Претензий пока нет»", () => {
    mockFetch.mockResolvedValue([]);
    render(<ClaimsPanel initial={[]} />);
    expect(screen.getByText("Претензий пока нет")).toBeInTheDocument();
  });

  it("сегмент «Решённые» оставляет только решённые претензии", () => {
    render(<ClaimsPanel initial={claims} />);
    expect(screen.getByText("Корпус A")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Решённые" }));

    expect(screen.getByText("Крышка B")).toBeInTheDocument();
    expect(screen.queryByText("Корпус A")).not.toBeInTheDocument();
    expect(screen.queryByText("Вал C")).not.toBeInTheDocument();
  });

  it("поиск фильтрует строки по изделию", () => {
    render(<ClaimsPanel initial={claims} />);
    fireEvent.change(screen.getByPlaceholderText("Поиск по изделию, наряду, поставщику"), {
      target: { value: "Вал" },
    });
    expect(screen.getByText("Вал C")).toBeInTheDocument();
    expect(screen.queryByText("Корпус A")).not.toBeInTheDocument();
    expect(screen.queryByText("Крышка B")).not.toBeInTheDocument();
  });

  it("правка поставщика на открытой претензии зовёт updateClaim при blur", async () => {
    mockUpdate.mockResolvedValue(claim({ id: 3, supplier: "Новый поставщик" }));
    render(<ClaimsPanel initial={claims} />);

    // у открытой претензии №3 поле-инпут поставщика с текущим значением
    const input = screen.getByDisplayValue("Поставщик X");
    fireEvent.change(input, { target: { value: "Новый поставщик" } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith(3, { supplier: "Новый поставщик" }),
    );
  });

  it("кнопка «Претензия» открывает дровер и «Завести» зовёт createClaim", async () => {
    mockCreate.mockResolvedValue(claim({ id: 99, item: "Новое изделие" }));
    render(<ClaimsPanel initial={claims} />);

    fireEvent.click(screen.getByRole("button", { name: /Претензия/ }));
    expect(screen.getByRole("heading", { name: "Новая претензия" })).toBeInTheDocument();

    const drawer = screen.getByRole("heading", { name: "Новая претензия" }).closest("div")
      ?.parentElement as HTMLElement;
    // поле «Изделие» — первый инпут в дровере
    const itemField = within(drawer).getByText("Изделие").parentElement as HTMLElement;
    fireEvent.change(within(itemField).getByRole("textbox"), {
      target: { value: "Новое изделие" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Завести" }));

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({ item: "Новое изделие", claim_type: "брак", qty_affected: 0 }),
      ),
    );
  });

  it("сбой создания показывает ошибку и не закрывает дровер", async () => {
    mockCreate.mockResolvedValue(null); // отказ бэка
    render(<ClaimsPanel initial={claims} />);

    fireEvent.click(screen.getByRole("button", { name: /Претензия/ }));
    fireEvent.click(screen.getByRole("button", { name: "Завести" }));

    expect(await screen.findByText("Не удалось завести претензию")).toBeInTheDocument();
    // дровер остался открыт
    expect(screen.getByRole("heading", { name: "Новая претензия" })).toBeInTheDocument();
  });

  it("урегулирование открытой претензии зовёт updateClaim со статусом resolved", async () => {
    mockUpdate.mockResolvedValue(claim({ id: 1, status: "resolved", resolution: "заменили" }));
    render(<ClaimsPanel initial={claims} />);

    // кнопка-галочка «Урегулировать (решена)» есть у каждой открытой претензии
    fireEvent.click(screen.getAllByTitle("Урегулировать (решена)")[0]);
    expect(screen.getByRole("heading", { name: "Урегулировать претензию" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Решено" }));

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith(1, { status: "resolved", resolution: "" }),
    );
  });

  it("отклонение претензии шлёт статус rejected с текстом резолюции", async () => {
    mockUpdate.mockResolvedValue(claim({ id: 1, status: "rejected", resolution: "не наш брак" }));
    render(<ClaimsPanel initial={claims} />);

    fireEvent.click(screen.getAllByTitle("Отклонить претензию")[0]);
    expect(screen.getByRole("heading", { name: "Отклонить претензию" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Поставщик компенсировал/), {
      target: { value: "не наш брак" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Отклонить" }));

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith(1, { status: "rejected", resolution: "не наш брак" }),
    );
  });
});
