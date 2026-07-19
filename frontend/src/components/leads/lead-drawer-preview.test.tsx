import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// next/link → простая <a> (jsdom); тяжёлые соседние компоненты глушим — тестируем
// собственную логику drawer-preview изолированно.
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/components/leads/lead-attachments", () => ({
  LeadAttachments: () => <div data-testid="attachments" />,
}));
vi.mock("@/components/kanban/catalog-picker-modal", () => ({
  CatalogPickerModal: () => <div data-testid="catalog" />,
}));
vi.mock("@/components/kanban/product-picker", () => ({
  useProductPicker: () => ({
    skus: [],
    stock: {},
    pickedRows: [],
    addSkuWithQty: vi.fn(),
    setRowPrice: vi.fn(),
    reset: vi.fn(),
  }),
}));
vi.mock("@/lib/api", () => ({
  fetchLeadManagers: vi.fn().mockResolvedValue([
    { name: "Иванов И.И.", regions: ["минск"], products: ["лист"], load: 2 },
    { name: "Петрова А.С.", regions: ["брест"], products: ["арматура"], load: 0 },
  ]),
  fetchLeadItems: vi.fn().mockResolvedValue([]),
  saveLeadItems: vi.fn().mockResolvedValue(true),
  convertLead: vi.fn(),
  commitLeadItemsToDeal: vi.fn(),
  issueDocument: vi.fn(),
  linkLeadContact: vi.fn(),
}));

import { LeadDrawerPreview } from "@/components/leads/lead-drawer-preview";
import * as api from "@/lib/api";
import type { Lead, LeadCartItem } from "@/lib/types";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

function makeLead(overrides: Partial<Lead> = {}): Lead {
  return {
    id: 7,
    source: "site",
    name: "Иван",
    company: "ООО Тест",
    phone: "+375291112233",
    email: "",
    region: "Минск",
    product: "лист",
    message: "",
    status: "new",
    score: 0,
    qualification: "",
    reason: "",
    assignedTo: "",
    funnel: "",
    rejectReason: "",
    nextStepAt: null,
    nextStepNote: "",
    ...overrides,
  };
}

const items: LeadCartItem[] = [
  { skuId: 1, skuCode: "A1", name: "Лист 5мм", qty: 2, price: 100, discountPct: 0 },
  { skuId: 2, skuCode: "B2", name: "Уголок", qty: 3, price: 50, discountPct: 0 },
];

function noopHandlers() {
  return {
    onClose: vi.fn(),
    onQualify: vi.fn(),
    onRoute: vi.fn(),
    onConvert: vi.fn(),
    onCall: vi.fn(),
    onReject: vi.fn(),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mock(api.fetchLeadItems).mockResolvedValue([]);
});

describe("LeadDrawerPreview", () => {
  it("Escape закрывает превью открытого лида", () => {
    const h = noopHandlers();
    render(<LeadDrawerPreview lead={makeLead()} busy={false} {...h} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(h.onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape НЕ вызывает onClose когда лид не открыт (lead=null)", () => {
    const h = noopHandlers();
    render(<LeadDrawerPreview lead={null} busy={false} {...h} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(h.onClose).not.toHaveBeenCalled();
  });

  // --- Отклонение лида + рецикл «не сейчас» (Цикл 16) ---
  it("отказ «не сейчас» показывает пресеты отсрочки и передаёт выбранные дни в onReject", async () => {
    const h = noopHandlers();
    render(<LeadDrawerPreview lead={makeLead()} busy={false} {...h} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "не сейчас" } });
    // Дефолт отсрочки — 90 дней → текст кнопки.
    expect(screen.getByRole("button", { name: "Отложить на 90 дн" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "30 дн" }));
    fireEvent.click(screen.getByRole("button", { name: "Отложить на 30 дн" }));

    expect(h.onReject).toHaveBeenCalledWith(7, "не сейчас", 30);
  });

  it("обычная причина отказа зовёт onReject без snoozeDays", () => {
    const h = noopHandlers();
    render(<LeadDrawerPreview lead={makeLead()} busy={false} {...h} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "дубль" } });
    // Пресетов отсрочки для обычной причины нет.
    expect(screen.queryByRole("button", { name: "30 дн" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Отклонить" }));

    expect(h.onReject).toHaveBeenCalledWith(7, "дубль", undefined);
  });

  it("секция отказа скрыта для уже распределённого лида", () => {
    const h = noopHandlers();
    render(<LeadDrawerPreview lead={makeLead({ status: "routed" })} busy={false} {...h} />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  // --- Привязка контакта к компании (Цикл 11) ---
  it("привязка контакта: created=true → сообщение о добавлении", async () => {
    const h = noopHandlers();
    mock(api.linkLeadContact).mockResolvedValue({
      contactId: 5,
      counterpartyId: 42,
      created: true,
      fullName: "Иван Петров",
    });
    render(
      <LeadDrawerPreview lead={makeLead({ counterpartyId: 42 })} busy={false} {...h} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Добавить контакт в компанию/ }));

    await waitFor(() => expect(api.linkLeadContact).toHaveBeenCalledWith(7));
    expect(
      await screen.findByText("Контакт «Иван Петров» добавлен в компанию"),
    ).toBeInTheDocument();
  });

  it("привязка контакта: created=false → сообщение «уже был в компании»", async () => {
    const h = noopHandlers();
    mock(api.linkLeadContact).mockResolvedValue({
      contactId: 5,
      counterpartyId: 42,
      created: false,
      fullName: "Иван Петров",
    });
    render(
      <LeadDrawerPreview lead={makeLead({ counterpartyId: 42 })} busy={false} {...h} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Добавить контакт в компанию/ }));

    expect(
      await screen.findByText("Контакт «Иван Петров» уже был в компании"),
    ).toBeInTheDocument();
  });

  it("привязка контакта: серверная ошибка (error) отображается как есть", async () => {
    const h = noopHandlers();
    mock(api.linkLeadContact).mockResolvedValue({ error: "Компания не найдена" });
    render(
      <LeadDrawerPreview lead={makeLead({ counterpartyId: 42 })} busy={false} {...h} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Добавить контакт в компанию/ }));

    expect(await screen.findByText("Компания не найдена")).toBeInTheDocument();
  });

  it("привязка контакта: сетевой сбой (null) даёт дружелюбное сообщение", async () => {
    const h = noopHandlers();
    mock(api.linkLeadContact).mockResolvedValue(null);
    render(
      <LeadDrawerPreview lead={makeLead({ counterpartyId: 42 })} busy={false} {...h} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Добавить контакт в компанию/ }));

    expect(
      await screen.findByText("Не удалось добавить контакт — попробуйте ещё раз"),
    ).toBeInTheDocument();
  });

  it("секция привязки контакта отсутствует без counterpartyId", () => {
    const h = noopHandlers();
    render(<LeadDrawerPreview lead={makeLead()} busy={false} {...h} />);
    expect(
      screen.queryByRole("button", { name: /Добавить контакт в компанию/ }),
    ).not.toBeInTheDocument();
  });

  it("постоянник помечен ярлыком «Постоянник»", () => {
    const h = noopHandlers();
    render(
      <LeadDrawerPreview
        lead={makeLead({ counterpartyId: 42, customerKind: "regular" })}
        busy={false}
        {...h}
      />,
    );
    expect(screen.getByText("Постоянник")).toBeInTheDocument();
  });

  // --- Выбор менеджера и распределение ---
  it("выбор менеджера меняет ярлык кнопки и передаёт assignedTo в onRoute", async () => {
    const h = noopHandlers();
    render(
      <LeadDrawerPreview lead={makeLead({ status: "qualified" })} busy={false} {...h} />,
    );

    const mgr = (await screen.findByText("Иванов И.И.")).closest("button") as HTMLButtonElement;
    fireEvent.click(mgr);

    const routeBtn = screen.getByRole("button", { name: "Распределить → Иванов И.И." });
    fireEvent.click(routeBtn);
    expect(h.onRoute).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ assignedTo: "Иванов И.И." }),
    );
  });

  it("повторный клик по менеджеру снимает выбор (кнопка снова «Распределить»)", async () => {
    const h = noopHandlers();
    render(
      <LeadDrawerPreview lead={makeLead({ status: "qualified" })} busy={false} {...h} />,
    );

    const mgr = (await screen.findByText("Иванов И.И.")).closest("button") as HTMLButtonElement;
    fireEvent.click(mgr);
    expect(screen.getByRole("button", { name: "Распределить → Иванов И.И." })).toBeInTheDocument();
    fireEvent.click(mgr);
    expect(screen.getByRole("button", { name: "Распределить" })).toBeInTheDocument();
  });

  it("кнопка «Квалифицировать» заблокирована и меняет текст для квалифицированного лида", () => {
    const h = noopHandlers();
    render(
      <LeadDrawerPreview lead={makeLead({ status: "qualified" })} busy={false} {...h} />,
    );
    const btn = screen.getByRole("button", { name: "✓ Квалифицирован" });
    expect(btn).toBeDisabled();
  });

  // --- Список сохранённого КП ---
  it("сохранённые позиции показывают строки и итог по числу позиций", async () => {
    const h = noopHandlers();
    mock(api.fetchLeadItems).mockResolvedValue(items);
    render(<LeadDrawerPreview lead={makeLead({ status: "routed" })} busy={false} {...h} />);

    expect(await screen.findByText("Лист 5мм")).toBeInTheDocument();
    expect(screen.getByText("Уголок")).toBeInTheDocument();
    expect(screen.getByText("Итого · 2 поз.")).toBeInTheDocument();
  });

  it("для отклонённого лида кнопка «Подобрать товары» скрыта", () => {
    const h = noopHandlers();
    render(<LeadDrawerPreview lead={makeLead({ status: "rejected" })} busy={false} {...h} />);
    expect(
      screen.queryByRole("button", { name: /Подобрать товары/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Подбор не выполнялся.")).toBeInTheDocument();
  });

  // --- Цепочка «В сделку + счёт» ---
  it("успешная цепочка: конвертация → позиции → счёт, ссылка на счёт и onConverted", async () => {
    const h = noopHandlers();
    const onConverted = vi.fn();
    mock(api.fetchLeadItems).mockResolvedValue(items);
    mock(api.convertLead).mockResolvedValue({ deal_id: 55 });
    mock(api.commitLeadItemsToDeal).mockResolvedValue({ ok: 2, total: 2 });
    mock(api.issueDocument).mockResolvedValue({ ok: true, renderUrl: "/api/inv/55" });

    render(
      <LeadDrawerPreview
        lead={makeLead({ status: "routed" })}
        busy={false}
        onConverted={onConverted}
        {...h}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "⚡ В сделку + счёт" }));

    const invLink = await screen.findByText("Открыть счёт →");
    expect(invLink.closest("a")).toHaveAttribute("href", "/api/inv/55");
    expect(onConverted).toHaveBeenCalledWith(7, 55);
    expect(api.commitLeadItemsToDeal).toHaveBeenCalledWith("55", "ООО Тест", items);
    expect(api.issueDocument).toHaveBeenCalledWith("55", "invoice");
  });

  it("цепочка: сделка не создалась → ошибка, позиции и счёт не трогаются", async () => {
    const h = noopHandlers();
    const onConverted = vi.fn();
    mock(api.fetchLeadItems).mockResolvedValue(items);
    mock(api.convertLead).mockResolvedValue({}); // без deal_id

    render(
      <LeadDrawerPreview
        lead={makeLead({ status: "routed" })}
        busy={false}
        onConverted={onConverted}
        {...h}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "⚡ В сделку + счёт" }));

    expect(
      await screen.findByText("Сделка не создалась — сервис sales не ответил"),
    ).toBeInTheDocument();
    expect(onConverted).not.toHaveBeenCalled();
    expect(api.commitLeadItemsToDeal).not.toHaveBeenCalled();
    expect(api.issueDocument).not.toHaveBeenCalled();
  });

  it("цепочка: часть позиций не перенеслась → стоп до счёта", async () => {
    const h = noopHandlers();
    mock(api.fetchLeadItems).mockResolvedValue(items);
    mock(api.convertLead).mockResolvedValue({ deal_id: 55 });
    mock(api.commitLeadItemsToDeal).mockResolvedValue({ ok: 1, total: 2 });

    render(<LeadDrawerPreview lead={makeLead({ status: "routed" })} busy={false} {...h} />);

    fireEvent.click(await screen.findByRole("button", { name: "⚡ В сделку + счёт" }));

    expect(
      await screen.findByText(/Перенеслись 1 из 2 позиций/),
    ).toBeInTheDocument();
    expect(api.issueDocument).not.toHaveBeenCalled();
  });

  it("цепочка: счёт не выставился → ошибка при готовых сделке и позициях", async () => {
    const h = noopHandlers();
    mock(api.fetchLeadItems).mockResolvedValue(items);
    mock(api.convertLead).mockResolvedValue({ deal_id: 55 });
    mock(api.commitLeadItemsToDeal).mockResolvedValue({ ok: 2, total: 2 });
    mock(api.issueDocument).mockResolvedValue({ ok: false });

    render(<LeadDrawerPreview lead={makeLead({ status: "routed" })} busy={false} {...h} />);

    fireEvent.click(await screen.findByRole("button", { name: "⚡ В сделку + счёт" }));

    expect(
      await screen.findByText("Счёт не выставлен (сделка и позиции готовы)"),
    ).toBeInTheDocument();
  });

  it("кнопка «⚡ В сделку + счёт» не показывается без сохранённых позиций", async () => {
    const h = noopHandlers();
    mock(api.fetchLeadItems).mockResolvedValue([]);
    render(<LeadDrawerPreview lead={makeLead({ status: "routed" })} busy={false} {...h} />);
    // Ждём загрузку менеджеров, чтобы эффекты отработали.
    await screen.findByText("Иванов И.И.").catch(() => null);
    expect(
      screen.queryByRole("button", { name: "⚡ В сделку + счёт" }),
    ).not.toBeInTheDocument();
  });

  // --- Конвертированный лид ---
  it("конвертированный лид ведёт ссылкой на сделку, без кнопки «В сделку»", () => {
    const h = noopHandlers();
    render(
      <LeadDrawerPreview
        lead={makeLead({ status: "converted", dealId: 99 })}
        busy={false}
        {...h}
      />,
    );
    expect(screen.getByText("Открыть сделку").closest("a")).toHaveAttribute(
      "href",
      "/crm/deals/99",
    );
    expect(screen.queryByRole("button", { name: "В сделку" })).not.toBeInTheDocument();
  });

  it("кнопка «Позвонить» вызывает onCall с лидом", () => {
    const h = noopHandlers();
    const lead = makeLead();
    render(<LeadDrawerPreview lead={lead} busy={false} {...h} />);
    fireEvent.click(screen.getByRole("button", { name: /Позвонить/ }));
    expect(h.onCall).toHaveBeenCalledWith(lead);
  });

  it("без телефона кнопка «Позвонить» не рендерится", () => {
    const h = noopHandlers();
    render(<LeadDrawerPreview lead={makeLead({ phone: "" })} busy={false} {...h} />);
    expect(screen.queryByRole("button", { name: /Позвонить/ })).not.toBeInTheDocument();
  });
});
