import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// next/link → простая <a> в jsdom; API модуля — мок (компонент тестируем изолированно)
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
// next/navigation.useRouter — нужен для router.push в двойном клике по лиду (drawer-pattern).
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock("@/lib/api", () => ({
  createLead: vi.fn(),
  qualifyLead: vi.fn(),
  routeLead: vi.fn(),
  rejectLead: vi.fn(),
  convertLead: vi.fn(),
  expressLead: vi.fn(),
  // call-popup использует createDealTask для постановки задачи из звонка
  createDealTask: vi.fn().mockResolvedValue(true),
  // LeadDrawerPreview рендерит <LeadAttachments> — полоска вложений лида
  fetchLeadAttachments: vi.fn().mockResolvedValue([]),
  uploadLeadAttachment: vi.fn(),
  leadAttachmentDownloadUrl: (leadId: number, attachmentId: number) =>
    `/api/leads/${leadId}/attachments/${attachmentId}/download`,
  // Цикл 3: подбор товара (КП) на лиде + цепочка «В сделку + счёт»
  fetchLeadItems: vi.fn().mockResolvedValue([]),
  saveLeadItems: vi.fn().mockResolvedValue(true),
  commitLeadItemsToDeal: vi.fn().mockResolvedValue({ ok: 1, total: 1 }),
  issueDocument: vi.fn().mockResolvedValue({ ok: true, message: "✅ Счёт выставлен", renderUrl: "/api/x" }),
  // Пикер менеджера в drawer (ручная раздача лида) — список для «Кому передать».
  fetchLeadManagers: vi.fn().mockResolvedValue([
    { name: "Иванов И.И.", regions: ["минск"], products: ["лист"], load: 2 },
    { name: "Петрова А.С.", regions: ["брест"], products: ["арматура"], load: 0 },
    { name: "Сидоров С.С.", regions: ["минск", "минская"], products: ["прокат"], load: 5 },
  ]),
  // Панель «Качество источников» (Цикл 4) — грузится лениво при открытии.
  fetchLeadSourceStats: vi.fn().mockResolvedValue([]),
  // Цикл 5: план/факт лидоруба — грузится на маунте (null = панель скрыта в тестах).
  fetchLeadPlan: vi.fn().mockResolvedValue(null),
  saveLeadPlan: vi.fn().mockResolvedValue(null),
  // Цикл 6: конвейер «Разобрать целевых».
  expressBulkLeads: vi.fn().mockResolvedValue({ expressed: [], skippedNonTarget: 0 }),
  // Цикл 7: скорборд передач продавцам — грузится лениво при открытии.
  fetchLeadHandoffStats: vi.fn().mockResolvedValue([]),
  // Цикл 15: недозвон — попытка контакта + срок перезвона.
  logLeadAttempt: vi.fn(),
  // Живой поллинг приёма: null = сетевая ошибка/нет обновления (доску не трогаем).
  fetchLeadsClient: vi.fn().mockResolvedValue(null),
  // Чистая функция (локальное naive-время → naive-UTC) — в тестах passthrough.
  localToNaiveUtc: (s: string) => s,
}));

import { LeadsWorkspace } from "@/components/leads/leads-workspace";
import * as api from "@/lib/api";
import type { Lead } from "@/lib/types";

const lead: Lead = {
  id: 1,
  source: "site",
  name: "Иван",
  company: "ООО Тест",
  region: "Минск",
  product: "лист",
  message: "Нужен лист 5 мм",
  status: "new",
  score: 0,
  qualification: "",
  reason: "",
  assignedTo: "",
  funnel: "",
  rejectReason: "",
  nextStepAt: null,
  nextStepNote: "",
};

// naive UTC ISO (как отдаёт бэкенд, без "Z") — N минут назад, для чипа ожидания SLA.
function isoMinutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60000).toISOString().replace("Z", "");
}

// Превью-дровер больше НЕ открывается сам при заходе (его модальный бэкдроп глушил
// клики по карточкам) — открываем явным 1-кликом по карточке и ждём диалог
// (в LeadCard одиночный клик срабатывает через таймер 230мс).
async function openPreview(id: number) {
  fireEvent.click(screen.getByText(`№ ЛИД-${id}`));
  return await screen.findByRole("dialog");
}

beforeEach(() => vi.clearAllMocks());

describe("LeadsWorkspace", () => {
  it("рендерит инбокс лидов и счётчик новых", () => {
    render(<LeadsWorkspace initialLeads={[lead]} />);
    expect(screen.getByText("Приём лидов")).toBeInTheDocument();
    expect(screen.getByText(/Новых: 1 из 1/)).toBeInTheDocument();
    expect(screen.getAllByText("ООО Тест").length).toBeGreaterThan(0);
  });

  it("квалификация обновляет балл, вердикт и показывает AI-обоснование", async () => {
    (api.qualifyLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1,
      status: "qualified",
      score: 85,
      qualification: "target",
      reason: "есть телефон, указан продукт",
      ai_rationale: "AI-обоснование квалификации",
      model: "qwen",
    });
    render(<LeadsWorkspace initialLeads={[lead]} />);

    // открываем превью явным кликом → действие доступно в правой панели
    await openPreview(1);
    fireEvent.click(screen.getByRole("button", { name: "Квалифицировать" }));

    await waitFor(() => expect(api.qualifyLead).toHaveBeenCalledWith(1));
    expect(await screen.findByText("AI-обоснование квалификации")).toBeInTheDocument();
    expect(screen.getAllByText(/85 · целевой/).length).toBeGreaterThan(0);
  });

  it("распределение показывает назначенного менеджера и воронку", async () => {
    (api.routeLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1,
      status: "routed",
      assigned_to: "Иванов И.И.",
      funnel: "new",
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, status: "qualified", score: 70, qualification: "target" }]} />);

    await openPreview(1);
    fireEvent.click(await screen.findByRole("button", { name: "Распределить" }));

    await waitFor(() =>
      expect(api.routeLead).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ assignedTo: undefined }),
      ),
    );
    // менеджер показан и на карточке, и в drawer «Распределение» → несколько совпадений
    expect((await screen.findAllByText(/Иванов И\.И\./)).length).toBeGreaterThan(0);
    expect(screen.getByText(/Новые клиенты/)).toBeInTheDocument();
  });

  it("пикер менеджера в drawer — выбор и «Распределить → <имя>» уходят ручным выбором", async () => {
    (api.routeLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1,
      status: "routed",
      assigned_to: "Петрова А.С.",
      funnel: "new",
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, status: "qualified", score: 70, qualification: "target" }]} />);

    await openPreview(1);
    // список менеджеров подгружается асинхронно (fetchLeadManagers)
    expect(await screen.findByText("Кому передать")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Петрова А\.С\./ }));

    fireEvent.click(screen.getByRole("button", { name: /Распределить → Петрова А\.С\./ }));

    await waitFor(() =>
      expect(api.routeLead).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ assignedTo: "Петрова А.С." }),
      ),
    );
  });

  it("кнопка «Принять лид» открывает форму приёма", () => {
    render(<LeadsWorkspace initialLeads={[]} />);
    expect(screen.getByText(/Лидов пока нет/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Принять лид/ }));
    const dialog = screen.getByText("Принять лид", { selector: "h3" }).closest("form");
    expect(dialog).not.toBeNull();
    expect(within(dialog as HTMLElement).getByPlaceholderText("ООО ...")).toBeInTheDocument();
  });

  it("конвертация распределённого лида показывает ссылку на сделку", async () => {
    (api.convertLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      lead_id: 1,
      deal_id: 42,
      number: "CRM-LEAD-1",
      status: "converted",
    });
    render(
      <LeadsWorkspace
        initialLeads={[{ ...lead, status: "routed", assignedTo: "Иванов И.И.", funnel: "new" }]}
      />,
    );
    await openPreview(1);
    fireEvent.click(screen.getByRole("button", { name: "В сделку" }));
    await waitFor(() => expect(api.convertLead).toHaveBeenCalledWith(1));
    const link = await screen.findByRole("link", { name: /Открыть сделку/ });
    expect(link).toHaveAttribute("href", "/crm/deals/42");
  });

  it("сбой конвертации показывает ошибку, а не молчит (лид не считается обработанным)", async () => {
    (api.convertLead as ReturnType<typeof vi.fn>).mockResolvedValue(null); // сетевой сбой/ошибка
    render(
      <LeadsWorkspace
        initialLeads={[{ ...lead, status: "routed", assignedTo: "Иванов И.И.", funnel: "new" }]}
      />,
    );
    await openPreview(1);
    fireEvent.click(screen.getByRole("button", { name: "В сделку" }));
    await waitFor(() => expect(api.convertLead).toHaveBeenCalledWith(1));
    expect(await screen.findByText(/Не удалось конвертировать/)).toBeInTheDocument();
    // лид остаётся распределённым (не переехал в «converted» молча)
    expect(screen.queryByRole("link", { name: /Открыть сделку/ })).not.toBeInTheDocument();
  });

  it("приём лида через форму добавляет его в инбокс", async () => {
    (api.createLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...lead,
      id: 99,
      company: "ООО Новый Лид",
    });
    render(<LeadsWorkspace initialLeads={[]} />);
    fireEvent.click(screen.getByRole("button", { name: /Принять лид/ }));
    const form = screen.getByText("Принять лид", { selector: "h3" }).closest("form") as HTMLElement;
    fireEvent.change(within(form).getByPlaceholderText("ООО ..."), {
      target: { value: "ООО Новый Лид" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Принять" }));
    await waitFor(() => expect(api.createLead).toHaveBeenCalled());
    expect((await screen.findAllByText("ООО Новый Лид")).length).toBeGreaterThan(0);
  });

  it("без лидов показывает подсказку выбрать лид", () => {
    render(<LeadsWorkspace initialLeads={[]} />);
    expect(screen.getByText(/Выберите лид/)).toBeInTheDocument();
  });

  it("отображает статусы «В сделке» и «Отклонён»", async () => {
    render(
      <LeadsWorkspace
        initialLeads={[
          { ...lead, id: 2, status: "converted", dealId: 5 },
          { ...lead, id: 3, status: "rejected" },
        ]}
      />,
    );
    expect(screen.getAllByText("В сделке").length).toBeGreaterThan(0);
    expect(screen.getByText("Отклонён")).toBeInTheDocument();
    // открываем превью конвертированного → в панели ссылка на сделку
    await openPreview(2);
    expect(screen.getByRole("link", { name: /Открыть сделку/ })).toHaveAttribute("href", "/crm/deals/5");
  });

  it("квалификация — прямо с карточки канбана, без захода в drawer (Слайс 1 кокпита)", async () => {
    (api.qualifyLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1,
      status: "qualified",
      score: 90,
      qualification: "target",
      reason: "полный профиль",
    });
    // второй лид НЕ выбран по умолчанию (drawer открыт на первом) — клик по его
    // карточной кнопке не должен зависеть от состояния drawer/preview.
    render(
      <LeadsWorkspace
        initialLeads={[
          { ...lead, id: 1 },
          { ...lead, id: 2, company: "ООО Второй" },
        ]}
      />,
    );
    const buttons = screen.getAllByRole("button", { name: "✅ Квалифицировать" });
    expect(buttons).toHaveLength(2); // по одной на карточку — не зависит от drawer
    fireEvent.click(buttons[1]); // карточка ЛИД-2 (не выбран в drawer по умолчанию)
    await waitFor(() => expect(api.qualifyLead).toHaveBeenCalledWith(2));
  });

  it("панель показывает контакты, нецелевой вердикт, распределение и AI-обоснование", async () => {
    render(
      <LeadsWorkspace
        initialLeads={[
          {
            ...lead,
            id: 4,
            name: "Пётр",
            company: "ООО Полный",
            phone: "+375290000000",
            email: "p@x.by",
            status: "routed",
            score: 30,
            qualification: "non-target",
            reason: "мало данных",
            assignedTo: "Сидоров С.С.",
            funnel: "regular",
            aiRationale: "AI-пояснение по лиду",
          },
        ]}
      />,
    );
    await openPreview(4);
    expect(screen.getByText("+375290000000")).toBeInTheDocument();
    expect(screen.getByText("p@x.by")).toBeInTheDocument();
    expect(screen.getAllByText(/нецелевой/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Сидоров С\.С\./).length).toBeGreaterThan(0);
    expect(screen.getByText("AI-пояснение по лиду")).toBeInTheDocument();
    expect(screen.getByText(/Постоянные/)).toBeInTheDocument(); // воронка regular
  });

  it("отказ — выбор причины и клик «Отклонить» зовёт rejectLead", async () => {
    (api.rejectLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1,
      status: "rejected",
      reject_reason: "дубль",
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, status: "qualified", score: 70, qualification: "target" }]} />);

    await openPreview(1);
    expect(await screen.findByText("Отклонить лид")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "дубль" } });

    fireEvent.click(screen.getByRole("button", { name: "Отклонить" }));

    // третий аргумент — snoozeDays (Цикл 16), для обычных причин undefined
    await waitFor(() => expect(api.rejectLead).toHaveBeenCalledWith(1, "дубль", undefined));
    expect(await screen.findByText("дубль", { selector: "div" })).toBeInTheDocument();
    expect(screen.getAllByText("Отклонён").length).toBeGreaterThan(0);
  });

  it("раздача со следующим шагом передаёт nextStepAt/nextStepNote в routeLead", async () => {
    (api.routeLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1,
      status: "routed",
      assigned_to: "Иванов И.И.",
      funnel: "new",
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, status: "qualified", score: 70, qualification: "target" }]} />);

    await openPreview(1);
    expect(await screen.findByText("Кому передать")).toBeInTheDocument();
    const datetimeInput = document.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    fireEvent.change(datetimeInput, { target: { value: "2026-07-05T10:00" } });
    fireEvent.change(screen.getByPlaceholderText("Заметка..."), {
      target: { value: "Перезвонить после обеда" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Распределить" }));

    await waitFor(() =>
      expect(api.routeLead).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          nextStepAt: "2026-07-05T10:00",
          nextStepNote: "Перезвонить после обеда",
        }),
      ),
    );
  });

  it("чип ожидания на карточке «Новые» подсвечивается при задержке дольше 15 минут", () => {
    // Цикл 14: SLA считается рабочими часами (9-18) — пиним «сейчас» в середину дня,
    // иначе ночной/утренний прогон CI даст 0 рабочих минут и тест соврёт.
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 6, 11, 12, 0, 0));
    try {
      render(
        <LeadsWorkspace
          initialLeads={[
            { ...lead, id: 1, createdAt: isoMinutesAgo(20) },
            { ...lead, id: 2, createdAt: isoMinutesAgo(5) },
          ]}
        />,
      );
      const chips = screen.getAllByTitle("Ожидает реакции с момента приёма");
      const overdue = chips.find((c) => c.textContent?.includes("20"));
      const fresh = chips.find((c) => c.textContent?.includes("5"));
      expect(overdue).toBeDefined();
      expect(overdue?.className).toMatch(/red/);
      expect(fresh).toBeDefined();
      expect(fresh?.className).not.toMatch(/red/);
    } finally {
      vi.useRealTimers();
    }
  });

  it("Цикл 14: ночной лид утром не «горит» — ждёт рабочие минуты, а не часы", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 6, 11, 9, 10, 0)); // утро, 9:10 локального времени
    try {
      // вчера 23:00 ЛОКАЛЬНОГО времени → naive-UTC строка, как отдаёт бэкенд
      // (через локальный Date — тест не зависит от таймзоны машины CI)
      const nightIso = new Date(2026, 6, 10, 23, 0, 0).toISOString().replace("Z", "");
      render(<LeadsWorkspace initialLeads={[{ ...lead, id: 1, createdAt: nightIso }]} />);
      const chip = screen.getByTitle("Ожидает реакции с момента приёма");
      // 10 рабочих минут (9:00→9:10), не «13 ч»: без пожара и без эскалации
      expect(chip.textContent).toContain("10 мин");
      expect(chip.className).not.toMatch(/red/);
    } finally {
      vi.useRealTimers();
    }
  });

  it("кнопка «⚡ Экспресс» показана на карточке нового лида с высоким баллом и скрыта при низком", () => {
    render(
      <LeadsWorkspace
        initialLeads={[
          { ...lead, id: 1, score: 70, qualification: "target" },
          { ...lead, id: 2, score: 20, qualification: "non-target", company: "ООО Слабый" },
        ]}
      />,
    );
    expect(screen.getAllByRole("button", { name: "⚡ Экспресс" })).toHaveLength(1);
  });

  it("экспресс — клик по пресету (по умолчанию) и «Передать» вызывает expressLead с ожидаемыми полями", async () => {
    (api.expressLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...lead,
      id: 1,
      score: 70,
      qualification: "target",
      status: "routed",
      assignedTo: "Иванов И.И.",
      funnel: "new",
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, id: 1, score: 70, qualification: "target" }]} />);

    fireEvent.click(screen.getByRole("button", { name: "⚡ Экспресс" }));
    expect(await screen.findByText("Кому")).toBeInTheDocument();

    // пресет по умолчанию — «Позвонить завтра 10:00», клик «Передать» без доп. выбора (2 клика)
    fireEvent.click(screen.getByRole("button", { name: "Передать" }));

    await waitFor(() => expect(api.expressLead).toHaveBeenCalled());
    const [calledId, calledOpts] = (api.expressLead as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(calledId).toBe(1);
    expect(calledOpts.assignedTo).toBeUndefined();
    expect(calledOpts.nextStepNote).toBe("Позвонить");
    expect(calledOpts.nextStepAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);

    // после успеха лид ушёл в «Распределение» — поповер закрылся
    expect(screen.queryByText("Кому")).not.toBeInTheDocument();
  });

  it("экспресс — выбор другого пресета передаёт его note/at вместо дефолтного", async () => {
    (api.expressLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...lead,
      id: 1,
      score: 70,
      qualification: "target",
      status: "routed",
      assignedTo: "Петров П.П.",
      funnel: "new",
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, id: 1, score: 70, qualification: "target" }]} />);

    fireEvent.click(screen.getByRole("button", { name: "⚡ Экспресс" }));
    fireEvent.click(await screen.findByRole("button", { name: "Без шага" }));
    fireEvent.click(screen.getByRole("button", { name: "Передать" }));

    await waitFor(() =>
      expect(api.expressLead).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ nextStepAt: undefined, nextStepNote: undefined }),
      ),
    );
  });

  it("экспресс — 422 «не целевой» показывает сообщение в поповере, не двигая лид", async () => {
    (api.expressLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      error: "Лид не целевой (балл 20) — экспресс недоступен, квалифицируй вручную",
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, id: 1, score: 70, qualification: "target" }]} />);

    fireEvent.click(screen.getByRole("button", { name: "⚡ Экспресс" }));
    fireEvent.click(await screen.findByRole("button", { name: "Передать" }));

    expect(await screen.findByText(/не целевой/)).toBeInTheDocument();
    // поповер остался открыт, лид не сдвинулся — кнопка экспресс всё ещё на карточке
    expect(screen.getByRole("button", { name: "⚡ Экспресс" })).toBeInTheDocument();
  });

  it("Цикл 3: карточка лида показывает бейдж КП «N поз.» при подобранных товарах", () => {
    render(
      <LeadsWorkspace
        initialLeads={[{ ...lead, id: 1, itemsCount: 2, itemsTotal: 750 }]}
      />,
    );
    expect(screen.getByText(/2 поз\./)).toBeInTheDocument();
  });

  it("Цикл 3: цепочка «В сделку + счёт» зовёт convert → перенос позиций → счёт по порядку", async () => {
    (api.fetchLeadItems as ReturnType<typeof vi.fn>).mockResolvedValue([
      { skuId: 7, skuCode: "6СТ-190", name: "АКБ 190", qty: 2, price: 300, discountPct: 0 },
    ]);
    (api.convertLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      lead_id: 1,
      deal_id: 42,
      status: "converted",
    });
    render(
      <LeadsWorkspace
        initialLeads={[
          { ...lead, id: 1, status: "routed", assignedTo: "Иванов И.И.", funnel: "new", itemsCount: 1 },
        ]}
      />,
    );

    await openPreview(1);
    // кнопка появляется, когда подгрузились сохранённые позиции (fetchLeadItems)
    const chainBtn = await screen.findByRole("button", { name: /В сделку \+ счёт/ });
    fireEvent.click(chainBtn);

    await waitFor(() => expect(api.issueDocument).toHaveBeenCalledWith("42", "invoice"));
    expect(api.convertLead).toHaveBeenCalledWith(1);
    expect(api.commitLeadItemsToDeal).toHaveBeenCalledWith(
      "42",
      "ООО Тест",
      expect.arrayContaining([expect.objectContaining({ skuId: 7, qty: 2 })]),
    );
    // порядок шагов: convert → позиции → счёт
    const convertOrder = (api.convertLead as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0];
    const commitOrder = (api.commitLeadItemsToDeal as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0];
    const invoiceOrder = (api.issueDocument as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0];
    expect(convertOrder).toBeLessThan(commitOrder);
    expect(commitOrder).toBeLessThan(invoiceOrder);

    // после успеха лид помечен converted → в футере ссылка на сделку
    expect(await screen.findByRole("link", { name: /Открыть сделку/ })).toHaveAttribute(
      "href",
      "/crm/deals/42",
    );
  });

  it("KPI «Ждут реакции >15м» считает только новые лиды старше 15 минут", () => {
    render(
      <LeadsWorkspace
        initialLeads={[
          { ...lead, id: 1, createdAt: isoMinutesAgo(20) }, // new, просрочен
          { ...lead, id: 2, createdAt: isoMinutesAgo(5) }, // new, свежий
          { ...lead, id: 3, status: "qualified", createdAt: isoMinutesAgo(30) }, // не new — не считается
        ]}
      />,
    );
    const tile = screen.getByText("Ждут реакции >15м").closest("div")?.parentElement;
    expect(tile).toHaveTextContent("1");
  });

  it("Цикл 13: переданный лид показывает возраст «у продавца» и просроченный шаг", () => {
    render(
      <LeadsWorkspace
        initialLeads={[
          {
            ...lead,
            id: 1,
            status: "routed",
            assignedTo: "Иванов И.И.",
            funnel: "new",
            routedAt: isoMinutesAgo(30 * 60), // 30 часов у продавца → жёлтая зона
            nextStepAt: isoMinutesAgo(120), // шаг просрочен на 2 часа
            nextStepNote: "Позвонить",
          },
        ]}
      />,
    );
    expect(screen.getByTitle(/У продавца с момента передачи/)).toBeInTheDocument();
    expect(screen.getByText(/шаг просрочен/)).toBeInTheDocument();
  });

  it("Цикл 13: converted без сделки дольше 10 минут — тревога «сделка не создана»", () => {
    render(
      <LeadsWorkspace
        initialLeads={[
          { ...lead, id: 1, status: "converted", convertedAt: isoMinutesAgo(15) }, // dealId нет
          { ...lead, id: 2, status: "converted", dealId: 5, convertedAt: isoMinutesAgo(15) },
        ]}
      />,
    );
    // тревога только у лида БЕЗ deal_id (событие потерялось), у нормального — нет
    expect(screen.getAllByText("⚠ сделка не создана")).toHaveLength(1);
  });

  it("Цикл 13: шапка «Распределение» показывает Σ КП в работе и зависших >24ч", () => {
    render(
      <LeadsWorkspace
        initialLeads={[
          {
            ...lead,
            id: 1,
            status: "routed",
            assignedTo: "Иванов И.И.",
            routedAt: isoMinutesAgo(10),
            itemsCount: 2,
            itemsTotal: 5000,
          },
          {
            ...lead,
            id: 2,
            status: "routed",
            assignedTo: "Петров П.П.",
            company: "ООО Висяк",
            routedAt: isoMinutesAgo(30 * 60), // >24ч — завис
          },
        ]}
      />,
    );
    expect(screen.getByText(/Σ КП в работе/)).toBeInTheDocument();
    expect(screen.getByText(/1 висят >24ч/)).toBeInTheDocument();
  });

  it("Цикл 14: «В сделку» с карточки переносит позиции КП в созданную сделку", async () => {
    (api.convertLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      lead_id: 1,
      deal_id: 42,
      status: "converted",
    });
    (api.fetchLeadItems as ReturnType<typeof vi.fn>).mockResolvedValue([
      { skuId: 7, skuCode: "6СТ-190", name: "АКБ 190", qty: 2, price: 300, discountPct: 0 },
    ]);
    (api.commitLeadItemsToDeal as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: 1, total: 1 });
    render(
      <LeadsWorkspace
        initialLeads={[
          {
            ...lead,
            id: 1,
            status: "routed",
            assignedTo: "Иванов И.И.",
            funnel: "new",
            itemsCount: 1,
            itemsTotal: 600,
          },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "⚡ В сделку" }));
    await waitFor(() =>
      expect(api.commitLeadItemsToDeal).toHaveBeenCalledWith(
        "42",
        "ООО Тест",
        expect.arrayContaining([expect.objectContaining({ skuId: 7, qty: 2 })]),
      ),
    );
  });

  it("Цикл 14: конвертация лида без КП не дёргает перенос позиций", async () => {
    (api.convertLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      lead_id: 1,
      deal_id: 43,
      status: "converted",
    });
    render(
      <LeadsWorkspace
        initialLeads={[{ ...lead, id: 1, status: "routed", assignedTo: "Иванов И.И.", funnel: "new" }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "⚡ В сделку" }));
    await waitFor(() => expect(api.convertLead).toHaveBeenCalledWith(1));
    expect(api.fetchLeadItems).not.toHaveBeenCalled();
    expect(api.commitLeadItemsToDeal).not.toHaveBeenCalled();
  });

  it("Цикл 15: кнопка «Недозвон» фиксирует попытку и показывает чип перезвона", async () => {
    (api.logLeadAttempt as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...lead,
      id: 1,
      attemptCount: 1,
      callbackAt: new Date(Date.now() + 2 * 3600_000).toISOString().replace("Z", ""),
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, id: 1 }]} />);

    fireEvent.click(screen.getByRole("button", { name: "Недозвон" }));

    await waitFor(() => expect(api.logLeadAttempt).toHaveBeenCalledWith(1));
    expect(await screen.findByText(/☎ 1/)).toBeInTheDocument();
  });

  it("Цикл 15: просроченный перезвон — красный чип «просрочен»", () => {
    render(
      <LeadsWorkspace
        initialLeads={[{ ...lead, id: 1, attemptCount: 2, callbackAt: isoMinutesAgo(30) }]}
      />,
    );
    const chip = screen.getByText(/☎ 2 · просрочен/);
    expect(chip.className).toMatch(/red/);
  });

  it("Цикл 15: повторное касание клиента — бейдж «↑ повтор»", () => {
    render(
      <LeadsWorkspace
        initialLeads={[{ ...lead, id: 1, lastTouchAt: isoMinutesAgo(5) }]}
      />,
    );
    expect(screen.getByText("↑ повтор")).toBeInTheDocument();
  });

  it("Цикл 16: отказ «не сейчас» показывает пресеты отсрочки и шлёт snoozeDays", async () => {
    (api.rejectLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1,
      status: "rejected",
      reject_reason: "не сейчас",
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, status: "qualified", score: 70, qualification: "target" }]} />);

    await openPreview(1);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "не сейчас" } });
    // пресеты отсрочки появились; выбираем 30 дней
    fireEvent.click(await screen.findByRole("button", { name: "30 дн" }));
    fireEvent.click(screen.getByRole("button", { name: "Отложить на 30 дн" }));

    await waitFor(() => expect(api.rejectLead).toHaveBeenCalledWith(1, "не сейчас", 30));
  });

  it("Цикл 16: проснувшийся лид — бейдж «⏰ проснулся», отложенные — в KPI", () => {
    render(
      <LeadsWorkspace
        initialLeads={[
          // дата возврата в прошлом + статус new = проснулся (wake-on-read бэка)
          { ...lead, id: 1, status: "new", snoozeUntil: isoMinutesAgo(60) },
          // ещё спит: rejected с датой в будущем → считается в «⏰ Отложенные»
          {
            ...lead,
            id: 2,
            status: "rejected",
            rejectReason: "не сейчас",
            company: "ООО Спит",
            snoozeUntil: new Date(Date.now() + 30 * 86400_000).toISOString().replace("Z", ""),
          },
        ]}
      />,
    );
    expect(screen.getByText("⏰ проснулся")).toBeInTheDocument();
    const tile = screen.getByText("⏰ Отложенные").closest("div")?.parentElement;
    expect(tile).toHaveTextContent("1");
  });

  it("Цикл 16: у проснувшегося лида SLA считается от пробуждения, а не от старого createdAt", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 6, 11, 12, 0, 0));
    try {
      render(
        <LeadsWorkspace
          initialLeads={[
            {
              ...lead,
              id: 1,
              status: "new",
              createdAt: isoMinutesAgo(90 * 24 * 60), // создан 90 дней назад
              snoozeUntil: isoMinutesAgo(10), // проснулся 10 минут назад
            },
          ]}
        />,
      );
      const chip = screen.getByTitle("Ожидает реакции с момента приёма");
      // не «🔥 90 дн»: отсчёт от пробуждения → свежие минуты, чип не красный
      expect(chip.textContent).toContain("10 мин");
      expect(chip.className).not.toMatch(/red/);
    } finally {
      vi.useRealTimers();
    }
  });

  it("панель «Качество источников» грузит данные лениво при открытии и рендерит строки", async () => {
    (api.fetchLeadSourceStats as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        source: "site", utmCampaign: "leto-2026", total: 10, target: 8, converted: 5,
        rejected: 1, avgScore: 72, targetPct: 80, conversionPct: 50,
      },
      {
        source: "phone", utmCampaign: "", total: 6, target: 1, converted: 0,
        rejected: 4, avgScore: 20, targetPct: 16.7, conversionPct: 0,
      },
    ]);

    render(<LeadsWorkspace initialLeads={[lead]} />);
    expect(api.fetchLeadSourceStats).not.toHaveBeenCalled(); // не на маунте

    fireEvent.click(screen.getByRole("button", { name: /Качество источников/ }));
    expect(await screen.findByText(/leto-2026/)).toBeInTheDocument();
    expect(api.fetchLeadSourceStats).toHaveBeenCalledTimes(1);
    expect(screen.getByText("16.7%")).toBeInTheDocument(); // targetPct строки «Телефон»

    // повторное открытие не дёргает API заново (данные уже загружены)
    fireEvent.click(screen.getByRole("button", { name: /Скрыть/ }));
    fireEvent.click(screen.getByRole("button", { name: /Качество источников/ }));
    expect(api.fetchLeadSourceStats).toHaveBeenCalledTimes(1);
  });

  it("Цикл 6: «Разобрать целевых» зовёт expressBulkLeads и показывает итог разбора", async () => {
    (api.expressBulkLeads as ReturnType<typeof vi.fn>).mockResolvedValue({
      expressed: [1],
      skippedNonTarget: 0,
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, id: 1, score: 70, qualification: "target" }]} />);

    // счётчик в кнопке = число целевых новых лидов
    fireEvent.click(screen.getByRole("button", { name: /Разобрать целевых \(1\)/ }));

    await waitFor(() => expect(api.expressBulkLeads).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Разобрано целевых: 1/)).toBeInTheDocument();
  });

  it("Цикл 6: кнопка «Разобрать целевых» заблокирована, когда целевых новых лидов нет", () => {
    // низкий балл (< EXPRESS_SCORE_THRESHOLD) → не кандидат на конвейер
    render(<LeadsWorkspace initialLeads={[{ ...lead, id: 1, score: 20, qualification: "non-target" }]} />);
    const btn = screen.getByRole("button", { name: /Разобрать целевых \(0\)/ });
    expect(btn).toBeDisabled();
  });

  it("Цикл 6: горячая клавиша E запускает конвейер разбора целевых", async () => {
    (api.expressBulkLeads as ReturnType<typeof vi.fn>).mockResolvedValue({
      expressed: [1],
      skippedNonTarget: 0,
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, id: 1, score: 70, qualification: "target" }]} />);

    // фокус вне полей ввода → обработчик keydown срабатывает
    fireEvent.keyDown(document.body, { code: "KeyE" });

    await waitFor(() => expect(api.expressBulkLeads).toHaveBeenCalledTimes(1));
  });

  it("скорборд «Передачи продавцам» грузится лениво и рендерит зависших >24ч", async () => {
    (api.fetchLeadHandoffStats as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        manager: "Иванов И.И.", assigned: 5, converted: 2, pipeline: 10000,
        conversionPct: 40, pending: 2, pendingPipeline: 3000, stale: 1,
      },
    ]);
    render(<LeadsWorkspace initialLeads={[lead]} />);
    expect(api.fetchLeadHandoffStats).not.toHaveBeenCalled(); // не на маунте

    fireEvent.click(screen.getByRole("button", { name: /Передачи продавцам/ }));
    expect(await screen.findByText("Иванов И.И.")).toBeInTheDocument();
    expect(screen.getByText("⚠ 1")).toBeInTheDocument(); // зависший >24ч
    expect(api.fetchLeadHandoffStats).toHaveBeenCalledTimes(1);

    // повторное открытие не дёргает API заново
    fireEvent.click(screen.getByRole("button", { name: /Скрыть/ }));
    fireEvent.click(screen.getByRole("button", { name: /Передачи продавцам/ }));
    expect(api.fetchLeadHandoffStats).toHaveBeenCalledTimes(1);
  });

  it("Цикл 5: панель плана рендерится и «Сохранить норму» шлёт правки в saveLeadPlan", async () => {
    (api.fetchLeadPlan as ReturnType<typeof vi.fn>).mockResolvedValue({
      leadsTarget: 30, qualifiedTarget: 10, convertedTarget: 3, reactionTargetMin: 15,
      leadsFact: 5, qualifiedFact: 2, convertedFact: 0, reactionFactMin: 8,
    });
    render(<LeadsWorkspace initialLeads={[lead]} />);

    expect(await screen.findByText("Мой план на сегодня")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Норма/ })); // войти в редактирование
    fireEvent.change(screen.getByLabelText("Обработать"), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить норму" }));

    await waitFor(() =>
      expect(api.saveLeadPlan).toHaveBeenCalledWith(
        expect.objectContaining({ leadsTarget: 50, qualifiedTarget: 10, convertedTarget: 3, reactionTargetMin: 15 }),
      ),
    );
  });

  it("Цикл 8: умная маршрутизация показывает обоснование выбора менеджера (rationale)", async () => {
    (api.routeLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1, status: "routed", assigned_to: "Иванов И.И.", funnel: "new",
      rationale: "Иванов — лучшая конверсия по региону",
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, id: 1, status: "qualified", score: 70, qualification: "target" }]} />);

    // распределение прямо с карточки канбана
    fireEvent.click(screen.getByRole("button", { name: "🤝 Распределить" }));

    await waitFor(() => expect(api.routeLead).toHaveBeenCalledWith(1, undefined));
    expect(await screen.findByText(/Распределён → Иванов/)).toBeInTheDocument();
  });

  it("сбой квалификации с карточки показывает флеш-ошибку, лид остаётся новым", async () => {
    (api.qualifyLead as ReturnType<typeof vi.fn>).mockResolvedValue(null); // сетевой сбой
    render(<LeadsWorkspace initialLeads={[{ ...lead, id: 1 }]} />);

    fireEvent.click(screen.getByRole("button", { name: "✅ Квалифицировать" }));

    await waitFor(() => expect(api.qualifyLead).toHaveBeenCalledWith(1));
    expect(await screen.findByText(/Не удалось квалифицировать ЛИД-1/)).toBeInTheDocument();
    // не переехал в квалификацию — балл-бейдж «целевой» не появился
    expect(screen.queryByText(/целевой/)).not.toBeInTheDocument();
  });
});
