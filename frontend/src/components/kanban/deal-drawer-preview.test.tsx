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

function renderDrawer(onUpdateFields = vi.fn(), dealOverride: Deal = deal) {
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
      now={Date.now()}
    />,
  );
  return { onUpdateFields };
}

beforeEach(() => {
  vi.clearAllMocks();
  mock(api.fetchDocuments).mockResolvedValue([]);
  mock(api.fetchDealItems).mockResolvedValue([]);
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
  it("нет документов (или ошибка фетча — fetchDocuments сам гасит её в []) — блок не рендерится", async () => {
    renderDrawer();
    await waitFor(() => expect(api.fetchDocuments).toHaveBeenCalledWith("1"));
    expect(screen.queryByText("Документы")).toBeNull();
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
    expect(await screen.findByText("Документы")).toBeInTheDocument();
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
    const { onUpdateFields } = renderDrawer();
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
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Написать клиенту" }));
    const group = screen.getByRole("group", { name: "Написать клиенту" });
    fireEvent.click(within(group).getByRole("button", { name: "Напоминание об оплате" }));
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));

    expect(await screen.findByText("⚠️ Не отправилось")).toBeInTheDocument();
    expect(onUpdateFields).not.toHaveBeenCalled();
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
    const { onUpdateFields } = renderDrawer(vi.fn(), dealWithStep);
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
