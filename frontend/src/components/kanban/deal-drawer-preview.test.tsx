import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/lib/api", () => ({
  issueDocument: vi.fn(),
  fetchDocuments: vi.fn().mockResolvedValue([]),
  updateDeal: vi.fn().mockResolvedValue(true),
  fetchContacts: vi.fn().mockResolvedValue([]),
  fetchSkus: vi.fn().mockResolvedValue([]),
  fetchStock: vi.fn().mockResolvedValue([]),
  sendMessage: vi.fn(),
  aiDraftReply: vi.fn(),
  fetchDealItems: vi.fn().mockResolvedValue([]),
  requestApproval: vi.fn(),
  fetchLastOrder: vi.fn().mockResolvedValue([]), // цикл 14 — «Повторить заказ»
  addDealItem: vi.fn().mockResolvedValue(true),
  createPriceQuote: vi.fn().mockResolvedValue(true),
}));
vi.mock("@/lib/contracts-api", () => ({
  fetchContractTemplates: vi.fn().mockResolvedValue([]),
  prepareContract: vi.fn(),
  sendPackage: vi.fn(),
}));

import { DealDrawerPreview } from "@/components/kanban/deal-drawer-preview";
import * as api from "@/lib/api";
import * as contractsApi from "@/lib/contracts-api";
import type { Deal, Stage } from "@/lib/types";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const deal: Deal = {
  id: "1",
  number: "CRM-1",
  company: "ООО Карта",
  description: "Поставка металлопроката",
  amount: 1000,
  priority: "Средний",
  owner: "Иванов И.И.",
};

const stages: Stage[] = [
  { id: "invoice", title: "Счёт отправлен", color: "#000", count: 1, sum: 1000, deals: [deal] },
];

function renderDrawer(
  onUpdateFields = vi.fn(),
  dealOverride: Deal = deal,
  approvals?: Map<string, string>,
  onMessageSent = vi.fn(),
) {
  const stagesForDeal: Stage[] =
    dealOverride === deal
      ? stages
      : [{ id: "invoice", title: "Счёт отправлен", color: "#000", count: 1, sum: 1000, deals: [dealOverride] }];
  render(
    <DealDrawerPreview
      deal={dealOverride}
      stages={stagesForDeal}
      onClose={() => {}}
      onMoveStage={() => {}}
      onUpdateFields={onUpdateFields}
      onAddTask={() => {}}
      onWin={() => {}}
      onLose={() => {}}
      onMessageSent={onMessageSent}
      now={Date.now()}
      approvals={approvals}
    />,
  );
  return { onUpdateFields, onMessageSent };
}

beforeEach(() => {
  vi.clearAllMocks();
  mock(api.fetchDocuments).mockResolvedValue([]);
  mock(api.fetchDealItems).mockResolvedValue([]);
  mock(api.fetchLastOrder).mockResolvedValue([]);
  mock(api.addDealItem).mockResolvedValue(true);
  mock(api.createPriceQuote).mockResolvedValue(true);
  mock(contractsApi.fetchContractTemplates).mockResolvedValue([]);
  vi.stubGlobal(
    "open",
    vi.fn(() => ({ location: { href: "" }, close: vi.fn() })),
  );
});

describe("DealDrawerPreview — слайс 6 (A): авто-шаг после счёта", () => {
  it("успешный счёт → onUpdateFields с next_step «Проверить оплату…» (+3 дн); updateDeal НЕ дублируем", async () => {
    mock(api.issueDocument).mockResolvedValue({
      ok: true,
      message: "✅ Счёт СЧ-1 выставлен",
      renderUrl: "/api/sales/documents/9/render",
    });
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Счёт" }));

    expect(await screen.findByText(/Шаг: Проверить оплату/)).toBeInTheDocument();
    expect(api.issueDocument).toHaveBeenCalledWith("1", "invoice");
    expect(onUpdateFields).toHaveBeenCalledWith(
      "1",
      expect.objectContaining({
        next_step: expect.stringContaining("Проверить оплату"),
        next_step_at: expect.any(String),
      }),
    );
    // Фикс ревью 61fb9e9: onUpdateFields (владелец — deals-workspace.tsx) САМ шлёт сетевой
    // PATCH — drawer НЕ должен звать updateDeal напрямую (иначе дублирующий запрос).
    expect(api.updateDeal).not.toHaveBeenCalled();
  });

  it("неуспешный счёт (ok=false) — updateDeal НЕ вызван", async () => {
    mock(api.issueDocument).mockResolvedValue({ ok: false, message: "⚠️ Не удалось выставить счёт" });
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Счёт" }));
    await screen.findByText("⚠️ Не удалось выставить счёт");
    expect(api.updateDeal).not.toHaveBeenCalled();
  });
});

describe("DealDrawerPreview — слайс 7: варианты договора", () => {
  it("клик «Договор» раскрывает секцию и грузит шаблоны один раз", async () => {
    mock(contractsApi.fetchContractTemplates).mockResolvedValue([
      { id: 1, code: "supply-basic", name: "Поставка (базовый)" },
    ]);
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Договор" }));
    expect(await screen.findByRole("button", { name: "Поставка (базовый)" })).toBeInTheDocument();
    expect(contractsApi.fetchContractTemplates).toHaveBeenCalledTimes(1);
  });

  it("пустой список шаблонов → «Шаблонов нет»", async () => {
    mock(contractsApi.fetchContractTemplates).mockResolvedValue([]);
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Договор" }));
    expect(await screen.findByText("Шаблонов нет")).toBeInTheDocument();
  });

  it("клик по шаблону → prepareContract(dealId, code) + сообщение + шаг «Проверить согласование…» (+1 дн)", async () => {
    mock(contractsApi.fetchContractTemplates).mockResolvedValue([
      { id: 1, code: "supply-basic", name: "Поставка (базовый)" },
    ]);
    mock(contractsApi.prepareContract).mockResolvedValue({
      ok: true,
      message: "✅ Договор ДГ-1 отправлен на согласование",
      doc: {
        id: 1,
        kind: "contract",
        number: "ДГ-1",
        status: "pending_approval",
        onec_ref: null,
        amount: 1,
        valid_until: null,
        reserve_status: "none",
      },
    });
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Договор" }));
    fireEvent.click(await screen.findByRole("button", { name: "Поставка (базовый)" }));

    expect(await screen.findByText(/Шаг: Проверить согласование/)).toBeInTheDocument();
    expect(contractsApi.prepareContract).toHaveBeenCalledWith("1", "supply-basic");
    expect(onUpdateFields).toHaveBeenCalledWith(
      "1",
      expect.objectContaining({
        next_step: expect.stringContaining("Проверить согласование договора"),
        next_step_at: expect.any(String),
      }),
    );
    // Фикс ревью 61fb9e9: updateDeal НЕ зовём напрямую — onUpdateFields уже шлёт PATCH.
    expect(api.updateDeal).not.toHaveBeenCalled();
  });

  it("409 при подготовке по шаблону — message показан, шаг НЕ ставится", async () => {
    mock(contractsApi.fetchContractTemplates).mockResolvedValue([
      { id: 1, code: "supply-basic", name: "Поставка (базовый)" },
    ]);
    mock(contractsApi.prepareContract).mockResolvedValue({
      ok: false,
      message: "Договор по сделке уже подготовлен",
    });
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Договор" }));
    fireEvent.click(await screen.findByRole("button", { name: "Поставка (базовый)" }));
    expect(await screen.findByText("Договор по сделке уже подготовлен")).toBeInTheDocument();
    expect(api.updateDeal).not.toHaveBeenCalled();
  });

  it("«Форма клиента» → issueDocument(id, contract) + шаг «Вычитать договор клиента…» (+2 дн)", async () => {
    mock(api.issueDocument).mockResolvedValue({
      ok: true,
      message: "✅ Договор ДГ-2 отправлен на согласование",
    });
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Договор" }));
    fireEvent.click(await screen.findByRole("button", { name: "Оформить по форме клиента" }));

    expect(await screen.findByText(/Шаг: Вычитать договор клиента/)).toBeInTheDocument();
    expect(api.issueDocument).toHaveBeenCalledWith("1", "contract");
    expect(onUpdateFields).toHaveBeenCalledWith(
      "1",
      expect.objectContaining({
        next_step: expect.stringContaining("Вычитать договор клиента"),
        next_step_at: expect.any(String),
      }),
    );
    // Фикс ревью 61fb9e9: updateDeal НЕ зовём напрямую — onUpdateFields уже шлёт PATCH.
    expect(api.updateDeal).not.toHaveBeenCalled();
  });

  it("«Форма клиента» — ошибка → message показан, шаг НЕ ставится", async () => {
    mock(api.issueDocument).mockResolvedValue({ ok: false, message: "⚠️ Не удалось создать договор" });
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Договор" }));
    fireEvent.click(await screen.findByRole("button", { name: "Оформить по форме клиента" }));
    await screen.findByText("⚠️ Не удалось создать договор");
    expect(api.updateDeal).not.toHaveBeenCalled();
  });
});

describe("DealDrawerPreview — слайс 6 (B): блок «Документы»", () => {
  it("нет документов (или ошибка фетча — fetchDocuments сам гасит её в []) — блок статуса не рендерится", async () => {
    renderDrawer();
    await waitFor(() => expect(api.fetchDocuments).toHaveBeenCalledWith("1"));
    // Цикл 9: группа «Документы» (заголовок) всегда на месте — рендерится условно только
    // вложенный блок статуса последних счёта/договора, переименованный в «Статус документов»
    // (чтобы не дублировать заголовок группы).
    expect(screen.queryByText("Статус документов")).toBeNull();
  });

  it("счёт с valid_until в прошлом — «просрочен N дн», бейдж «резерв», ссылка «открыть»", async () => {
    mock(api.fetchDocuments).mockResolvedValue([
      {
        id: 9,
        kind: "invoice",
        number: "СЧ-1",
        status: "posted",
        onec_ref: null,
        amount: 5000,
        valid_until: "2000-01-01",
        reserve_status: "reserved",
      },
    ]);
    renderDrawer();
    // «Документы» — заголовок группы, виден всегда; ждём именно вложенный блок статуса,
    // который рендерится только после того, как fetchDocuments реально резолвнулся.
    expect(await screen.findByText("Статус документов")).toBeInTheDocument();
    expect(screen.getByText(/Счёт СЧ-1/)).toBeInTheDocument();
    expect(screen.getByText(/просрочен \d+ дн/)).toBeInTheDocument();
    expect(screen.getByText("резерв")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "открыть" })).toHaveAttribute(
      "href",
      "/api/sales/documents/9/render",
    );
  });

  it("договор — номер и статус", async () => {
    mock(api.fetchDocuments).mockResolvedValue([
      {
        id: 4,
        kind: "contract",
        number: "ДГ-2",
        status: "pending_approval",
        onec_ref: null,
        amount: 1,
        valid_until: null,
        reserve_status: "none",
      },
    ]);
    renderDrawer();
    expect(await screen.findByText(/Договор ДГ-2/)).toBeInTheDocument();
    expect(screen.getByText("На согласовании")).toBeInTheDocument();
  });
});

describe("DealDrawerPreview — слайс 8 (C): секция «Написать клиенту»", () => {
  it("канал по умолчанию whatsapp; клик по шаблону стадии подставляет текст в textarea", async () => {
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Написать клиенту" }));
    const group = screen.getByRole("group", { name: "Написать клиенту" });
    expect(within(group).getByRole("button", { name: "WhatsApp" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // deal в стадии invoice (см. `stages` выше) — шаблон из MESSAGE_TEMPLATES.invoice
    fireEvent.click(within(group).getByRole("button", { name: "Напоминание об оплате" }));
    expect(screen.getByLabelText("Текст сообщения клиенту")).toHaveValue(
      "Добрый день! Напоминаю: счёт №… действителен до …. Подтвердите, пожалуйста, оплату.",
    );
  });

  it("клик по каналу переключает выбранный канал (aria-pressed)", async () => {
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Написать клиенту" }));
    const group = screen.getByRole("group", { name: "Написать клиенту" });
    fireEvent.click(within(group).getByRole("button", { name: "Telegram" }));
    expect(within(group).getByRole("button", { name: "Telegram" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(group).getByRole("button", { name: "WhatsApp" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("«AI-черновик»: aiDraftReply → текст в textarea", async () => {
    mock(api.aiDraftReply).mockResolvedValue("Черновик от AI");
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Написать клиенту" }));
    fireEvent.click(screen.getByRole("button", { name: "AI-черновик" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Текст сообщения клиенту")).toHaveValue("Черновик от AI"),
    );
    expect(api.aiDraftReply).toHaveBeenCalledWith("1");
  });

  it("«AI-черновик»: null (AI выключен) → честный тост, textarea не трогаем", async () => {
    mock(api.aiDraftReply).mockResolvedValue(null);
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Написать клиенту" }));
    fireEvent.click(screen.getByRole("button", { name: "AI-черновик" }));
    expect(await screen.findByText("AI-слой выключен — черновик недоступен")).toBeInTheDocument();
    expect(screen.getByLabelText("Текст сообщения клиенту")).toHaveValue("");
  });

  it("«Отправить» disabled при пустом тексте", () => {
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Написать клиенту" }));
    expect(screen.getByRole("button", { name: "Отправить" })).toBeDisabled();
  });

  it("успешная отправка (у сделки нет шага) → тост + авто-шаг «Дождаться ответа клиента» (+2 дн)", async () => {
    mock(api.sendMessage).mockResolvedValue(true);
    const { onUpdateFields, onMessageSent } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Написать клиенту" }));
    const group = screen.getByRole("group", { name: "Написать клиенту" });
    fireEvent.click(within(group).getByRole("button", { name: "Напоминание об оплате" }));
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));

    expect(await screen.findByText("✅ Отправлено (WhatsApp) · Шаг: Дождаться ответа (2 дн)")).toBeInTheDocument();
    expect(api.sendMessage).toHaveBeenCalledWith(
      "1",
      "whatsapp",
      "Добрый день! Напоминаю: счёт №… действителен до …. Подтвердите, пожалуйста, оплату.",
    );
    expect(onUpdateFields).toHaveBeenCalledWith(
      "1",
      expect.objectContaining({
        next_step: "Дождаться ответа клиента",
        next_step_at: expect.any(String),
      }),
    );
    // Фикс ревью 61fb9e9: updateDeal НЕ зовём напрямую — onUpdateFields уже шлёт PATCH.
    expect(api.updateDeal).not.toHaveBeenCalled();
    // textarea очищается после успешной отправки
    expect(screen.getByLabelText("Текст сообщения клиенту")).toHaveValue("");
    // Цикл 17: гашение бейджа «клиент ждёт» — вызывающий (deals-workspace.tsx) шлёт
    // messages/read + сбрасывает inboundSignals по этому dealId.
    expect(onMessageSent).toHaveBeenCalledWith("1");
  });

  it("успешная отправка (у сделки УЖЕ есть шаг) → тост БЕЗ авто-шага, живой шаг не перетираем", async () => {
    mock(api.sendMessage).mockResolvedValue(true);
    const dealWithStep: Deal = { ...deal, nextStep: "Уже назначенный шаг" };
    const { onUpdateFields } = renderDrawer(vi.fn(), dealWithStep);
    fireEvent.click(screen.getByRole("button", { name: "Написать клиенту" }));
    const group = screen.getByRole("group", { name: "Написать клиенту" });
    fireEvent.click(within(group).getByRole("button", { name: "Напоминание об оплате" }));
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));

    expect(await screen.findByText("✅ Отправлено (WhatsApp)")).toBeInTheDocument();
    expect(screen.queryByText(/Шаг: Дождаться ответа/)).toBeNull();
    expect(onUpdateFields).not.toHaveBeenCalled();
  });

  it("ошибка отправки → тост «⚠️ Не отправилось», шаг не ставится", async () => {
    mock(api.sendMessage).mockResolvedValue(false);
    const { onUpdateFields, onMessageSent } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Написать клиенту" }));
    const group = screen.getByRole("group", { name: "Написать клиенту" });
    fireEvent.click(within(group).getByRole("button", { name: "Напоминание об оплате" }));
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));

    expect(await screen.findByText("⚠️ Не отправилось")).toBeInTheDocument();
    expect(onUpdateFields).not.toHaveBeenCalled();
    // Цикл 17: неуспешная отправка не гасит бейдж — клиент так и не получил сообщение.
    expect(onMessageSent).not.toHaveBeenCalled();
  });
});

describe("DealDrawerPreview — слайс 8 (D): кнопка «📦 Пакет клиенту»", () => {
  const postedInvoice = {
    id: 9,
    kind: "invoice",
    number: "СЧ-1",
    status: "posted",
    onec_ref: null,
    amount: 5000,
    valid_until: null,
    reserve_status: "none",
  };
  const postedContract = {
    id: 4,
    kind: "contract",
    number: "ДГ-2",
    status: "posted",
    onec_ref: null,
    amount: 1,
    valid_until: null,
    reserve_status: "none",
  };

  it("нет кнопки, если договор ещё pending_approval (честное отсутствие, не дизейбл)", async () => {
    mock(api.fetchDocuments).mockResolvedValue([
      postedInvoice,
      { ...postedContract, status: "pending_approval" },
    ]);
    renderDrawer();
    await screen.findByText("Документы");
    expect(screen.queryByRole("button", { name: "📦 Пакет клиенту" })).toBeNull();
  });

  it("нет кнопки, если договора нет вообще", async () => {
    mock(api.fetchDocuments).mockResolvedValue([postedInvoice]);
    renderDrawer();
    await screen.findByText("Документы");
    expect(screen.queryByRole("button", { name: "📦 Пакет клиенту" })).toBeNull();
  });

  it("счёт posted + договор posted → кнопка видима", async () => {
    mock(api.fetchDocuments).mockResolvedValue([postedInvoice, postedContract]);
    renderDrawer();
    expect(await screen.findByRole("button", { name: "📦 Пакет клиенту" })).toBeInTheDocument();
  });

  it("счёт paid + договор posted → кнопка тоже видима (paid — тот же признак у бэка)", async () => {
    mock(api.fetchDocuments).mockResolvedValue([{ ...postedInvoice, status: "paid" }, postedContract]);
    renderDrawer();
    expect(await screen.findByRole("button", { name: "📦 Пакет клиенту" })).toBeInTheDocument();
  });

  it("успех → тост + авто-шаг «Контроль получения пакета» (+1 дн), ПЕРЕТИРАЕТ уже назначенный шаг", async () => {
    mock(api.fetchDocuments).mockResolvedValue([postedInvoice, postedContract]);
    mock(contractsApi.sendPackage).mockResolvedValue({
      ok: true,
      message: "✅ Пакет отправлен: счёт + договор",
    });
    const dealWithStep: Deal = { ...deal, nextStep: "Уже назначенный шаг" };
    const { onUpdateFields, onMessageSent } = renderDrawer(vi.fn(), dealWithStep);
    fireEvent.click(await screen.findByRole("button", { name: "📦 Пакет клиенту" }));

    expect(
      await screen.findByText("✅ Пакет отправлен: счёт + договор · Шаг: Контроль получения пакета (1 дн)"),
    ).toBeInTheDocument();
    expect(contractsApi.sendPackage).toHaveBeenCalledWith("1");
    expect(onUpdateFields).toHaveBeenCalledWith(
      "1",
      expect.objectContaining({
        next_step: "Контроль получения пакета",
        next_step_at: expect.any(String),
      }),
    );
    // Фикс ревью 61fb9e9: updateDeal НЕ зовём напрямую — onUpdateFields уже шлёт PATCH.
    expect(api.updateDeal).not.toHaveBeenCalled();
    // Цикл 17: пакет тоже пишет исходящее сообщение в переписку — тот же гейт гашения.
    expect(onMessageSent).toHaveBeenCalledWith("1");
  });

  it("409 → тост с detail с бэка, шаг НЕ ставится", async () => {
    mock(api.fetchDocuments).mockResolvedValue([postedInvoice, postedContract]);
    mock(contractsApi.sendPackage).mockResolvedValue({
      ok: false,
      message: "Нужны проведённый счёт и согласованный договор",
    });
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(await screen.findByRole("button", { name: "📦 Пакет клиенту" }));

    expect(await screen.findByText("Нужны проведённый счёт и согласованный договор")).toBeInTheDocument();
    expect(onUpdateFields).not.toHaveBeenCalled();
  });
});

describe("DealDrawerPreview — слайс 9: мягкий скидочный гейт (защита прибыли)", () => {
  // deal.amount = 1000 (см. shared `deal` выше).
  const itemBelowMin = {
    id: 1,
    sku_id: 10,
    code: "A1",
    title: "Товар А",
    unit: "шт",
    qty: 10,
    last_price: 150,
    min_price: 150, // Σ = 10×150 = 1500 > 1000 — сумма сделки ниже минимума по прайсу
  };
  const itemAtMin = {
    id: 1,
    sku_id: 10,
    code: "A1",
    title: "Товар А",
    unit: "шт",
    qty: 5,
    last_price: 150,
    min_price: 150, // Σ = 5×150 = 750 <= 1000 — минимум соблюдён, гейта нет
  };

  it("плашка рендерится, когда сумма сделки ниже Σ(min_price × qty)", async () => {
    mock(api.fetchDealItems).mockResolvedValue([itemBelowMin]);
    renderDrawer();
    expect(await screen.findByText(/Сумма ниже минимума по прайсу/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Запросить одобрение РОП" })).toBeInTheDocument();
  });

  it("плашка НЕ рендерится, когда сумма сделки на уровне минимума или выше", async () => {
    mock(api.fetchDealItems).mockResolvedValue([itemAtMin]);
    renderDrawer();
    await waitFor(() => expect(api.fetchDealItems).toHaveBeenCalledWith("1"));
    expect(screen.queryByText(/Сумма ниже минимума по прайсу/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Запросить одобрение РОП" })).toBeNull();
  });

  it("плашка НЕ рендерится при пустых позициях сделки", async () => {
    mock(api.fetchDealItems).mockResolvedValue([]);
    renderDrawer();
    await waitFor(() => expect(api.fetchDealItems).toHaveBeenCalledWith("1"));
    expect(screen.queryByText(/Сумма ниже минимума по прайсу/)).toBeNull();
  });

  it("клик «Запросить одобрение РОП» → requestApproval(id, discount); успех (у сделки нет шага) → тост + авто-шаг", async () => {
    mock(api.fetchDealItems).mockResolvedValue([itemBelowMin]);
    mock(api.requestApproval).mockResolvedValue(true);
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(await screen.findByRole("button", { name: "Запросить одобрение РОП" }));

    expect(await screen.findByText("✅ Отправлено на одобрение РОП")).toBeInTheDocument();
    expect(api.requestApproval).toHaveBeenCalledWith("1", "discount");
    expect(onUpdateFields).toHaveBeenCalledWith(
      "1",
      expect.objectContaining({
        next_step: "Дождаться одобрения РОП",
        next_step_at: expect.any(String),
      }),
    );
  });

  it("успех при уже назначенном шаге — тост БЕЗ авто-шага, живой шаг не перетираем", async () => {
    mock(api.fetchDealItems).mockResolvedValue([itemBelowMin]);
    mock(api.requestApproval).mockResolvedValue(true);
    const dealWithStep: Deal = { ...deal, nextStep: "Уже назначенный шаг" };
    const { onUpdateFields } = renderDrawer(vi.fn(), dealWithStep);
    fireEvent.click(await screen.findByRole("button", { name: "Запросить одобрение РОП" }));

    expect(await screen.findByText("✅ Отправлено на одобрение РОП")).toBeInTheDocument();
    expect(onUpdateFields).not.toHaveBeenCalled();
  });

  it("ошибка → тост «⚠️ Не удалось отправить», шаг не ставится", async () => {
    mock(api.fetchDealItems).mockResolvedValue([itemBelowMin]);
    mock(api.requestApproval).mockResolvedValue(false);
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(await screen.findByRole("button", { name: "Запросить одобрение РОП" }));

    expect(await screen.findByText("⚠️ Не удалось отправить")).toBeInTheDocument();
    expect(onUpdateFields).not.toHaveBeenCalled();
  });
});

describe("DealDrawerPreview — цикл 14 (A): статус одобрения РОП", () => {
  it("approved — плашка «✅ скидка одобрена» (тон money)", async () => {
    renderDrawer(vi.fn(), deal, new Map([["1", "approved"]]));
    expect(await screen.findByText("✅ скидка одобрена")).toBeInTheDocument();
  });

  it("rejected — плашка «⛔ не одобрено»", async () => {
    renderDrawer(vi.fn(), deal, new Map([["1", "rejected"]]));
    expect(await screen.findByText("⛔ не одобрено")).toBeInTheDocument();
  });

  it("pending / нет согласований — плашка не рендерится (honest-empty, не шумим)", () => {
    renderDrawer(vi.fn(), deal, new Map([["1", "pending"]]));
    expect(screen.queryByText(/скидка одобрена/)).toBeNull();
    expect(screen.queryByText(/не одобрено/)).toBeNull();
  });
});

describe("DealDrawerPreview — цикл 14 (B): «Повторить заказ»", () => {
  const lastOrderItem = {
    id: 1,
    sku_id: 10,
    code: "A1",
    title: "Товар А",
    unit: "шт",
    qty: 3,
    last_price: 100,
    min_price: null,
  };

  it("успех: fetchLastOrder → addDealItem/createPriceQuote по КАЖДОЙ позиции + тост с числом", async () => {
    mock(api.fetchLastOrder).mockResolvedValue([lastOrderItem]);
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: /Повторить заказ/ }));

    expect(await screen.findByText("✅ Добавлено из прошлого заказа: 1/1")).toBeInTheDocument();
    expect(api.fetchLastOrder).toHaveBeenCalledWith("1");
    expect(api.addDealItem).toHaveBeenCalledWith("1", 10, 3);
    expect(api.createPriceQuote).toHaveBeenCalledWith("A1", "ООО Карта", 100);
  });

  it("прошлых заказов нет — honest-empty сообщение, без падения", async () => {
    mock(api.fetchLastOrder).mockResolvedValue([]);
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: /Повторить заказ/ }));

    expect(await screen.findByText("Прошлых заказов нет")).toBeInTheDocument();
    expect(api.addDealItem).not.toHaveBeenCalled();
  });
});

describe("DealDrawerPreview — пусто (deal === null)", () => {
  it("aside aria-hidden и без контента сделки", () => {
    render(
      <DealDrawerPreview
        deal={null}
        stages={stages}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={() => {}}
        now={Date.now()}
      />,
    );
    const aside = screen.getByRole("dialog", { hidden: true });
    expect(aside).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByText("№ CRM-1")).toBeNull();
  });
});

describe("DealDrawerPreview — сумма/вероятность/дни в стадии", () => {
  it("сумма + вероятность по дефолту стадии (invoice=70%) + взвешенно = amount×prob/100", () => {
    renderDrawer();
    expect(screen.getByText(/1\s000\s₽/)).toBeInTheDocument();
    expect(screen.getByText("70%")).toBeInTheDocument();
    expect(screen.getByText(/700\s₽/)).toBeInTheDocument();
  });

  it("явная deal.probability перебивает дефолт стадии", () => {
    const dealWithProb: Deal = { ...deal, probability: 20 };
    renderDrawer(vi.fn(), dealWithProb);
    expect(screen.getByText("20%")).toBeInTheDocument();
    // взвешенно = 1000 × 20 / 100 = 200
    expect(screen.getByText(/200\s₽/)).toBeInTheDocument();
  });

  it("дни в стадии ниже порога висяка (STUCK_DAYS=4) — без бейджа «висяк»", () => {
    const now = Date.now();
    const dealFresh: Deal = {
      ...deal,
      stageChangedAt: new Date(now - 2 * 86_400_000).toISOString(),
    };
    render(
      <DealDrawerPreview
        deal={dealFresh}
        stages={[{ id: "invoice", title: "Счёт отправлен", color: "#000", count: 1, sum: 1000, deals: [dealFresh] }]}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={() => {}}
        now={now}
      />,
    );
    expect(screen.getByText(/2 дн\./)).toBeInTheDocument();
    expect(screen.queryByText(/висяк/)).toBeNull();
  });

  it("дни в стадии ≥ порога (4) — бейдж «висяк»", () => {
    const now = Date.now();
    const dealStuck: Deal = {
      ...deal,
      stageChangedAt: new Date(now - 5 * 86_400_000).toISOString(),
    };
    render(
      <DealDrawerPreview
        deal={dealStuck}
        stages={[{ id: "invoice", title: "Счёт отправлен", color: "#000", count: 1, sum: 1000, deals: [dealStuck] }]}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={() => {}}
        now={now}
      />,
    );
    expect(screen.getByText(/5 дн\. · висяк/)).toBeInTheDocument();
  });
});

describe("DealDrawerPreview — причина отказа (SALES-40)", () => {
  it("lostReasonCode резолвится через reasonByCode + комментарий менеджера", () => {
    const lostDeal: Deal = { ...deal, lostReasonCode: "price", lostComment: "Дорого для клиента" };
    render(
      <DealDrawerPreview
        deal={lostDeal}
        stages={[{ id: "invoice", title: "Счёт отправлен", color: "#000", count: 1, sum: 1000, deals: [lostDeal] }]}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={() => {}}
        now={Date.now()}
        reasonByCode={new Map([["price", "Дорого / не прошли по цене"]])}
      />,
    );
    expect(screen.getByText(/Причина отказа: Дорого \/ не прошли по цене/)).toBeInTheDocument();
    expect(screen.getByText("Дорого для клиента")).toBeInTheDocument();
  });

  it("lostReasonCode без словаря — честный fallback на сырой код", () => {
    const lostDeal: Deal = { ...deal, lostReasonCode: "price" };
    render(
      <DealDrawerPreview
        deal={lostDeal}
        stages={[{ id: "invoice", title: "Счёт отправлен", color: "#000", count: 1, sum: 1000, deals: [lostDeal] }]}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={() => {}}
        now={Date.now()}
      />,
    );
    expect(screen.getByText(/Причина отказа: price/)).toBeInTheDocument();
  });
});

describe("DealDrawerPreview — шапка: закрепить/закрыть", () => {
  it("клик по звезде — onUpdateFields(id, { starred: true }) для незакреплённой сделки", () => {
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Закрепить" }));
    expect(onUpdateFields).toHaveBeenCalledWith("1", { starred: true });
  });

  it("клик по звезде уже закреплённой сделки — снимает закрепление (starred: false)", () => {
    const starredDeal: Deal = { ...deal, starred: true };
    const { onUpdateFields } = renderDrawer(vi.fn(), starredDeal);
    fireEvent.click(screen.getByRole("button", { name: "Снять закрепление" }));
    expect(onUpdateFields).toHaveBeenCalledWith("1", { starred: false });
  });

  it("клик «Закрыть превью» вызывает onClose", () => {
    const onClose = vi.fn();
    render(
      <DealDrawerPreview
        deal={deal}
        stages={stages}
        onClose={onClose}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={() => {}}
        now={Date.now()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Закрыть превью" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("DealDrawerPreview — движение по стадии (Группа 2)", () => {
  it("выбор стадии в select вызывает onMoveStage(dealId, targetStageId)", () => {
    const onMoveStage = vi.fn();
    const twoStages: Stage[] = [
      { id: "invoice", title: "Счёт отправлен", color: "#000", count: 1, sum: 1000, deals: [deal] },
      { id: "won", title: "Выиграна", color: "#0a0", count: 0, sum: 0, deals: [] },
    ];
    render(
      <DealDrawerPreview
        deal={deal}
        stages={twoStages}
        onClose={() => {}}
        onMoveStage={onMoveStage}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={() => {}}
        now={Date.now()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Стадия сделки"), { target: { value: "won" } });
    expect(onMoveStage).toHaveBeenCalledWith("1", "won");
  });

  it("кнопка «→ следующая стадия» видна и двигает в неё же", () => {
    const onMoveStage = vi.fn();
    const twoStages: Stage[] = [
      { id: "invoice", title: "Счёт отправлен", color: "#000", count: 1, sum: 1000, deals: [deal] },
      { id: "protected", title: "Резерв", color: "#000", count: 0, sum: 0, deals: [] },
    ];
    render(
      <DealDrawerPreview
        deal={deal}
        stages={twoStages}
        onClose={() => {}}
        onMoveStage={onMoveStage}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={() => {}}
        now={Date.now()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Резерв" }));
    expect(onMoveStage).toHaveBeenCalledWith("1", "protected");
  });

  it("сделка в последней стадии списка — кнопки «следующая стадия» нет", () => {
    render(
      <DealDrawerPreview
        deal={deal}
        stages={stages}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={() => {}}
        now={Date.now()}
      />,
    );
    expect(screen.queryByTitle(/Переместить в/)).toBeNull();
  });
});

describe("DealDrawerPreview — «Следующий шаг» inline-редактор", () => {
  it("нет шага → «—»; «Изменить» открывает поле с текущим текстом", () => {
    renderDrawer();
    expect(screen.getByText("—")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    expect(screen.getByPlaceholderText("Опишите следующий шаг…")).toHaveValue("");
  });

  it("Сохранить с изменённым текстом → onUpdateFields(id, { next_step: текст })", () => {
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    fireEvent.change(screen.getByPlaceholderText("Опишите следующий шаг…"), {
      target: { value: "  Позвонить завтра  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onUpdateFields).toHaveBeenCalledWith("1", { next_step: "Позвонить завтра" });
    // после сохранения редактор закрыт
    expect(screen.queryByPlaceholderText("Опишите следующий шаг…")).toBeNull();
  });

  it("Enter в поле коммитит так же, как «Сохранить»", () => {
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    const input = screen.getByPlaceholderText("Опишите следующий шаг…");
    fireEvent.change(input, { target: { value: "Написать письмо" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onUpdateFields).toHaveBeenCalledWith("1", { next_step: "Написать письмо" });
  });

  it("текст не изменился → «Сохранить» просто закрывает редактор, onUpdateFields НЕ вызван", () => {
    const dealWithStep: Deal = { ...deal, nextStep: "Уже назначенный шаг" };
    const { onUpdateFields } = renderDrawer(vi.fn(), dealWithStep);
    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onUpdateFields).not.toHaveBeenCalled();
    expect(screen.queryByPlaceholderText("Опишите следующий шаг…")).toBeNull();
  });

  it("Escape в поле — отмена без сохранения, восстанавливает исходный текст", () => {
    const dealWithStep: Deal = { ...deal, nextStep: "Уже назначенный шаг" };
    const { onUpdateFields } = renderDrawer(vi.fn(), dealWithStep);
    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    const input = screen.getByPlaceholderText("Опишите следующий шаг…");
    fireEvent.change(input, { target: { value: "черновик, который не сохранится" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByPlaceholderText("Опишите следующий шаг…")).toBeNull();
    expect(screen.getByText("Уже назначенный шаг")).toBeInTheDocument();
    expect(onUpdateFields).not.toHaveBeenCalled();
  });

  it("кнопка «Отмена» — то же, без сохранения", () => {
    const dealWithStep: Deal = { ...deal, nextStep: "Уже назначенный шаг" };
    const { onUpdateFields } = renderDrawer(vi.fn(), dealWithStep);
    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    fireEvent.change(screen.getByPlaceholderText("Опишите следующий шаг…"), {
      target: { value: "мимо" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.getByText("Уже назначенный шаг")).toBeInTheDocument();
    expect(onUpdateFields).not.toHaveBeenCalled();
  });
});

describe("DealDrawerPreview — «Быстрая задача»", () => {
  it("кнопка «Добавить» disabled при пустом вводе", () => {
    renderDrawer();
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
  });

  it("ввод текста и Enter добавляет задачу и очищает поле", () => {
    const onAddTask = vi.fn();
    render(
      <DealDrawerPreview
        deal={deal}
        stages={stages}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={onAddTask}
        onWin={() => {}}
        onLose={() => {}}
        now={Date.now()}
      />,
    );
    const input = screen.getByPlaceholderText("Позвонить, отправить КП, …");
    fireEvent.change(input, { target: { value: "Согласовать спецификацию" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onAddTask).toHaveBeenCalledWith("1", "Согласовать спецификацию");
    expect(input).toHaveValue("");
  });

  it("клик «Добавить» с trim() текста тоже добавляет задачу", () => {
    const onAddTask = vi.fn();
    render(
      <DealDrawerPreview
        deal={deal}
        stages={stages}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={onAddTask}
        onWin={() => {}}
        onLose={() => {}}
        now={Date.now()}
      />,
    );
    const input = screen.getByPlaceholderText("Позвонить, отправить КП, …");
    fireEvent.change(input, { target: { value: "  Заехать в офис  " } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    expect(onAddTask).toHaveBeenCalledWith("1", "Заехать в офис");
  });
});

describe("DealDrawerPreview — мета-список (ответственный/дата)", () => {
  it("ответственный отсутствует — «—»", () => {
    const dealNoOwner: Deal = { ...deal, owner: "" };
    renderDrawer(vi.fn(), dealNoOwner);
    // строка «Ответственный» всегда рендерится (Row обязательный)
    expect(screen.getByText("Ответственный").closest("div")).toBeInTheDocument();
  });

  it("closedDate в приоритете над expectedCloseDate — метка «Закрыта»", () => {
    const closedDeal: Deal = { ...deal, closedDate: "2026-01-05", expectedCloseDate: "2026-02-01" };
    renderDrawer(vi.fn(), closedDeal);
    expect(screen.getByText("Закрыта")).toBeInTheDocument();
    expect(screen.getByText("2026-01-05")).toBeInTheDocument();
  });

  it("без closedDate, с expectedCloseDate — метка «Ожид. закрытие»", () => {
    const openDeal: Deal = { ...deal, expectedCloseDate: "2026-02-01" };
    renderDrawer(vi.fn(), openDeal);
    expect(screen.getByText("Ожид. закрытие")).toBeInTheDocument();
    expect(screen.getByText("2026-02-01")).toBeInTheDocument();
  });

  it("нет ни одной даты — строка даты не рендерится вовсе", () => {
    renderDrawer();
    expect(screen.queryByText("Ожид. закрытие")).toBeNull();
    expect(screen.queryByText("Закрыта")).toBeNull();
  });
});

describe("DealDrawerPreview — цикл 15: факт-маржа в шапке скидочного гейта", () => {
  const itemBelowMin = {
    id: 1,
    sku_id: 10,
    code: "A1",
    title: "Товар А",
    unit: "шт",
    qty: 10,
    last_price: 150,
    min_price: 150,
  };

  it("margin_pct известен — «маржа N%» с тултипом охвата", async () => {
    mock(api.fetchDealItems).mockResolvedValue([itemBelowMin]);
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ margin_pct: 33, priced_count: 2, total_count: 3, reason: null }),
        } as Response),
      ),
    );
    renderDrawer();
    expect(await screen.findByText("маржа 33%")).toBeInTheDocument();
    expect(screen.getByText("маржа 33%")).toHaveAttribute("title", "оценено по 2 из 3 позиций");
  });

  it("маржа недоступна (fetch ok:false) — «маржа не рассчитана» с честной причиной в title", async () => {
    mock(api.fetchDealItems).mockResolvedValue([itemBelowMin]);
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false } as Response)),
    );
    renderDrawer();
    expect(await screen.findByText("маржа не рассчитана")).toBeInTheDocument();
  });

  it("margin.reason задан (фасад не подключён) — попадает в title честного плейсхолдера", async () => {
    mock(api.fetchDealItems).mockResolvedValue([itemBelowMin]);
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ margin_pct: null, priced_count: 0, total_count: 3, reason: "фасад не подключён" }),
        } as Response),
      ),
    );
    renderDrawer();
    const placeholder = await screen.findByText("маржа не рассчитана");
    expect(placeholder).toHaveAttribute("title", "фасад не подключён");
  });
});

describe("DealDrawerPreview — «Товар» открывает подбор товара", () => {
  it("клик по «Товар» открывает модалку подбора (CatalogPickerModal)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false, status: 500 } as Response)),
    );
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Товар" }));
    expect(await screen.findByRole("dialog", { name: "Подбор товара" })).toBeInTheDocument();
  });
});

describe("DealDrawerPreview — Группа 5: исход (Win/Lose)", () => {
  it("клик «Выиграна» вызывает onWin(dealId)", () => {
    const onWin = vi.fn();
    render(
      <DealDrawerPreview
        deal={deal}
        stages={stages}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={onWin}
        onLose={() => {}}
        now={Date.now()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Выиграна" }));
    expect(onWin).toHaveBeenCalledWith("1");
  });

  it("клик «Отказ» вызывает onLose(dealId)", () => {
    const onLose = vi.fn();
    render(
      <DealDrawerPreview
        deal={deal}
        stages={stages}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={onLose}
        now={Date.now()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Отказ" }));
    expect(onLose).toHaveBeenCalledWith("1");
  });

  it("сделка в стадии lost — блок Win/Lose скрыт (причина уже показана выше)", () => {
    const lostDeal: Deal = { ...deal };
    const lostStages: Stage[] = [
      { id: "lost", title: "Отказ", color: "#f00", count: 1, sum: 1000, deals: [lostDeal] },
    ];
    render(
      <DealDrawerPreview
        deal={lostDeal}
        stages={lostStages}
        onClose={() => {}}
        onMoveStage={() => {}}
        onUpdateFields={() => {}}
        onAddTask={() => {}}
        onWin={() => {}}
        onLose={() => {}}
        now={Date.now()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Выиграна" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отказ" })).toBeNull();
  });
});
