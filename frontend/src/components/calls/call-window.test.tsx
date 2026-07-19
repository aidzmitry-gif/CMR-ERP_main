import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ── Моки тяжёлых зависимостей (в стиле calls-workspace.test / product-picker не грузим ЕГР/остатки) ──
vi.mock("@/lib/api", () => ({
  createDeal: vi.fn(),
  createDealTask: vi.fn(),
  issueDocument: vi.fn(),
  lookupCounterparty: vi.fn(),
  updateDeal: vi.fn(),
}));

vi.mock("@/components/kanban/currency-context", () => ({
  useCurrency: () => ({ fmt: (n: number) => `${n}` }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/kanban/catalog-picker-modal", () => ({
  CatalogPickerModal: () => <div data-testid="catalog-modal">каталог</div>,
}));

// Управляемый стуб пикера — call-window сам решает ветку по picker.pickedRows/commitToDeal.
const stub = vi.hoisted(() => ({
  pickedRows: [] as { skuId: number; code: string; title: string; unit: string; qty: number; picked: boolean }[],
  orderTotal: 0,
  reset: vi.fn(),
  commitToDeal: vi.fn(),
  repeatLastOrder: vi.fn(),
}));

vi.mock("@/components/kanban/product-picker", () => ({
  useProductPicker: () => ({
    reset: stub.reset,
    pickedRows: stub.pickedRows,
    orderTotal: stub.orderTotal,
    commitToDeal: stub.commitToDeal,
    repeatLastOrder: stub.repeatLastOrder,
  }),
  ProductPicker: () => <div data-testid="product-picker" />,
  ProductPickerTotals: () => null,
}));

import { CallWindow, type CallContext } from "@/components/calls/call-window";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const dealCtx: CallContext = {
  kind: "deal",
  dealId: "42",
  number: "CRM-42",
  company: "ООО Ромашка",
  person: "Иван",
  phone: "+375291112233",
  stage: "Оплата",
};
const leadCtx: CallContext = {
  kind: "lead",
  leadId: 7,
  company: "ООО Лид",
  person: "Пётр",
  phone: "+375291110000",
  product: "Насосы",
};
const newCtx: CallContext = { kind: "new", phone: "+375291119999" };

const picked = () => [{ skuId: 1, code: "A1", title: "Насос", unit: "шт", qty: 2, picked: true }];

function renderCall(context: CallContext, onClose = vi.fn()) {
  render(<CallWindow context={context} onClose={onClose} />);
  return { onClose };
}

/** dialing → live: снять короткий дозвон (setTimeout 1200мс) внутри act. */
async function toLive() {
  await act(async () => {
    vi.advanceTimersByTime(1300);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  stub.pickedRows = [];
  stub.orderTotal = 0;
  stub.commitToDeal.mockResolvedValue({ ok: 1, total: 1 });
  stub.repeatLastOrder.mockResolvedValue(0);
  mock(api.createDeal).mockResolvedValue({ id: "99", number: "CRM-99" });
  mock(api.createDealTask).mockResolvedValue(true);
  mock(api.issueDocument).mockResolvedValue({ ok: true, message: "Счёт создан", renderUrl: "/r" });
  mock(api.lookupCounterparty).mockResolvedValue(null);
  mock(api.updateDeal).mockResolvedValue(true);
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("CallWindow — жизненный цикл фазы", () => {
  it("null-контекст ничего не рендерит", () => {
    const { container } = render(<CallWindow context={null} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("dialing → live: «Соединение…» сменяется разговором и таймером", async () => {
    renderCall(dealCtx);
    expect(screen.getByText("Соединение…")).toBeInTheDocument();
    await toLive();
    expect(screen.getByText("Разговор · ООО Ромашка")).toBeInTheDocument();
    expect(screen.getByText("00:00")).toBeInTheDocument();
  });

  it("«Завершить» открывает итог звонка (фаза done)", async () => {
    renderCall(dealCtx);
    await toLive();
    fireEvent.click(screen.getByRole("button", { name: /Завершить/ }));
    expect(screen.getByText("Итог звонка")).toBeInTheDocument();
  });
});

describe("CallWindow — закрытие", () => {
  it("Esc закрывает окно", async () => {
    const { onClose } = renderCall(dealCtx);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("клик по подложке закрывает, клик внутри — нет", async () => {
    const { onClose } = renderCall(dealCtx);
    fireEvent.click(screen.getByTestId("product-picker"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("CallWindow — реквизиты по УНП (лид/новый)", () => {
  it("невалидный УНП не дёргает бэкенд", async () => {
    renderCall(leadCtx);
    await toLive();
    fireEvent.change(screen.getByLabelText("УНП контрагента"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтянуть" }));
    expect(api.lookupCounterparty).not.toHaveBeenCalled();
    expect(screen.getByText("УНП — 9 цифр")).toBeInTheDocument();
  });

  it("валидный УНП по Enter подтягивает реквизиты из ЕГР", async () => {
    mock(api.lookupCounterparty).mockResolvedValue({
      unp: "191234567",
      name: "ООО Тест",
      address: "Минск, пр. Победителей 1",
      status: "Действующий",
    });
    renderCall(leadCtx);
    await toLive();
    const input = screen.getByLabelText("УНП контрагента");
    fireEvent.change(input, { target: { value: "191234567" } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
    });
    expect(api.lookupCounterparty).toHaveBeenCalledWith("191234567");
    expect(screen.getByText("ООО Тест")).toBeInTheDocument();
    expect(screen.getByText("Минск, пр. Победителей 1")).toBeInTheDocument();
  });

  it("УНП без совпадения показывает предупреждение", async () => {
    mock(api.lookupCounterparty).mockResolvedValue(null);
    renderCall(leadCtx);
    await toLive();
    fireEvent.change(screen.getByLabelText("УНП контрагента"), { target: { value: "999999999" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Подтянуть" }));
    });
    expect(screen.getByText("⚠️ По УНП ничего не найдено")).toBeInTheDocument();
  });

  it("у сделки блока реквизитов по УНП нет", async () => {
    renderCall(dealCtx);
    await toLive();
    expect(screen.queryByLabelText("УНП контрагента")).not.toBeInTheDocument();
  });
});

describe("CallWindow — заказ по контексту", () => {
  it("сделка: позиции добавляются в существующую сделку", async () => {
    stub.pickedRows = picked();
    renderCall(dealCtx);
    await toLive();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Добавить в сделку/ }));
    });
    expect(stub.commitToDeal).toHaveBeenCalledWith("42", "ООО Ромашка");
    expect(api.createDeal).not.toHaveBeenCalled();
    expect(screen.getByText("✅ В сделку добавлено позиций: 1/1")).toBeInTheDocument();
  });

  it("лид: создаётся быстрая сделка + задача-намерение и ссылка на неё", async () => {
    stub.pickedRows = picked();
    stub.orderTotal = 500;
    renderCall(leadCtx);
    await toLive();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Создать сделку с товаром/ }));
    });
    expect(api.createDeal).toHaveBeenCalledTimes(1);
    expect(mock(api.createDeal).mock.calls[0][0]).toMatchObject({ amount: 500, counterparty: "ООО Лид" });
    expect(mock(api.createDealTask).mock.calls[0][0]).toBe("lead:7");
    expect(screen.getByText("CRM-99")).toBeInTheDocument();
  });

  it("новый клиент: сделка создаётся без lead-задачи", async () => {
    stub.pickedRows = picked();
    renderCall(newCtx);
    await toLive();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Создать сделку с товаром/ }));
    });
    expect(api.createDeal).toHaveBeenCalledTimes(1);
    expect(api.createDealTask).not.toHaveBeenCalled();
    expect(screen.getByText("CRM-99")).toBeInTheDocument();
  });

  it("сбой createDeal показывает ошибку и не рендерит ссылку", async () => {
    stub.pickedRows = picked();
    mock(api.createDeal).mockResolvedValue(null);
    renderCall(leadCtx);
    await toLive();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Создать сделку с товаром/ }));
    });
    expect(screen.getByText("⚠️ Не удалось создать сделку")).toBeInTheDocument();
    expect(screen.queryByText("CRM-99")).not.toBeInTheDocument();
  });

  it("пустая корзина — CTA заблокирована", async () => {
    stub.pickedRows = [];
    renderCall(dealCtx);
    await toLive();
    expect(screen.getByRole("button", { name: /Добавить в сделку/ })).toBeDisabled();
  });
});

describe("CallWindow — документы и повтор (только сделка)", () => {
  it("счёт: успех открывает печать и ставит шаг «Проверить оплату»", async () => {
    const win = { location: { href: "" }, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    renderCall(dealCtx);
    await toLive();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Счёт" }));
    });
    expect(win.location.href).toBe("/r");
    expect(mock(api.updateDeal).mock.calls[0][0]).toBe("42");
    expect(mock(api.updateDeal).mock.calls[0][1]).toMatchObject({ next_step: "Проверить оплату счёта" });
    openSpy.mockRestore();
  });

  it("счёт: неуспех закрывает окно-пустышку и не трогает шаг", async () => {
    const win = { location: { href: "" }, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    mock(api.issueDocument).mockResolvedValue({ ok: false, message: "Нет позиций", renderUrl: null });
    renderCall(dealCtx);
    await toLive();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Счёт" }));
    });
    expect(win.close).toHaveBeenCalled();
    expect(api.updateDeal).not.toHaveBeenCalled();
    expect(screen.getByText("Нет позиций")).toBeInTheDocument();
    openSpy.mockRestore();
  });

  it("договор уходит на согласование", async () => {
    renderCall(dealCtx);
    await toLive();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Договор" }));
    });
    expect(api.issueDocument).toHaveBeenCalledWith("42", "contract");
  });

  it("повтор прошлого заказа: пусто → сообщение «не найдено»", async () => {
    stub.repeatLastOrder.mockResolvedValue(0);
    renderCall(dealCtx);
    await toLive();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Повторить прошлый заказ/ }));
    });
    expect(stub.repeatLastOrder).toHaveBeenCalledWith("42");
    expect(screen.getByText("Прошлых заказов этого контрагента не найдено")).toBeInTheDocument();
  });

  it("у лида нет кнопок «Счёт»/«Повторить прошлый заказ»", async () => {
    renderCall(leadCtx);
    await toLive();
    expect(screen.queryByRole("button", { name: "Счёт" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Повторить прошлый заказ/ })).not.toBeInTheDocument();
  });
});

describe("CallWindow — быстрая задача", () => {
  it("сделка: задача уходит на реальный id", async () => {
    renderCall(dealCtx);
    await toLive();
    const input = screen.getByPlaceholderText("Задача: перезвонить, выслать КП…");
    fireEvent.change(input, { target: { value: "перезвонить в 15:00" } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
    });
    expect(api.createDealTask).toHaveBeenCalledWith("42", { title: "перезвонить в 15:00" });
  });

  it("новый клиент: задача не уходит в бэкенд, а откладывается", async () => {
    renderCall(newCtx);
    await toLive();
    const input = screen.getByPlaceholderText("Задача: перезвонить, выслать КП…");
    fireEvent.change(input, { target: { value: "выслать КП" } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
    });
    expect(api.createDealTask).not.toHaveBeenCalled();
    expect(screen.getByText("✅ Заметка сохранена (привяжется к сделке)")).toBeInTheDocument();
  });
});

describe("CallWindow — модалка складского подбора", () => {
  it("«Подобрать ещё товар» открывает CatalogPickerModal", async () => {
    renderCall(dealCtx);
    await toLive();
    expect(screen.queryByTestId("catalog-modal")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Подобрать ещё товар/ }));
    expect(screen.getByTestId("catalog-modal")).toBeInTheDocument();
  });
});

describe("CallWindow — итог звонка (DoneSummary)", () => {
  it("без следующего шага — просто закрывает, бэкенд не трогает", async () => {
    const { onClose } = renderCall(dealCtx);
    await toLive();
    fireEvent.click(screen.getByRole("button", { name: /Завершить/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Сохранить и закрыть/ }));
    });
    expect(api.updateDeal).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("сделка: выбранный результат + пресет даты сохраняют шаг и задачу", async () => {
    const { onClose } = renderCall(dealCtx);
    await toLive();
    fireEvent.click(screen.getByRole("button", { name: /Завершить/ }));
    fireEvent.click(screen.getByRole("button", { name: "Отказ" }));
    fireEvent.click(screen.getByRole("button", { name: "Завтра 10:00" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Сохранить и закрыть/ }));
    });
    expect(mock(api.updateDeal).mock.calls[0][1]).toMatchObject({ next_step: "Отказ" });
    expect(mock(api.createDealTask).mock.calls[0][1].title).toBe("Следующий шаг: Отказ");
    expect(onClose).toHaveBeenCalled();
  });

  it("лид: следующий шаг сохраняется задачей на lead-ref (без updateDeal)", async () => {
    renderCall(leadCtx);
    await toLive();
    fireEvent.click(screen.getByRole("button", { name: /Завершить/ }));
    fireEvent.click(screen.getByRole("button", { name: "Завтра 10:00" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Сохранить и закрыть/ }));
    });
    expect(api.updateDeal).not.toHaveBeenCalled();
    expect(mock(api.createDealTask).mock.calls[0][0]).toBe("lead:7");
  });
});
