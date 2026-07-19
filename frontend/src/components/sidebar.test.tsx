import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// В этом тест-окружении нет window.localStorage — сайдбар читает его в try/catch,
// потому не падает, но остаётся свёрнутым (default collapsed). Стабаем хранилище так,
// чтобы эффект гидрации развернул rail (collapsed="0") и подписи попали в DOM.
beforeEach(() => {
  const store: Record<string, string> = { "aios-sidebar-collapsed": "0" };
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => {
      store[k] = v;
    },
    removeItem: (k: string) => {
      delete store[k];
    },
    clear: () => {
      for (const k of Object.keys(store)) delete store[k];
    },
  });
  mockUsePathname.mockReturnValue("/crm/deals");
  mockPush.mockClear();
  mockRefresh.mockClear();
});

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    className,
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

const { mockUsePathname, mockPush, mockRefresh } = vi.hoisted(() => ({
  mockUsePathname: vi.fn(() => "/crm/deals"),
  mockPush: vi.fn(),
  mockRefresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
  useRouter: () => ({ push: mockPush, refresh: mockRefresh }),
}));

import { Sidebar } from "@/components/sidebar";

describe("Sidebar", () => {
  it("рендерит навигацию по модулям, включая лиды и сделки", async () => {
    // Сайдбар по умолчанию — свёрнутый rail (collapsed); подписи модулей есть в DOM
    // только при развороте (showFull). Разворачиваем через localStorage-настройку,
    // которую читает эффект гидрации (COLLAPSED_KEY="aios-sidebar-collapsed").
    localStorage.setItem("aios-sidebar-collapsed", "0");
    render(<Sidebar />);
    expect(await screen.findByText("CRM")).toBeInTheDocument();
    expect(screen.getByText("Лиды")).toBeInTheDocument();
    expect(screen.getByText("Сделки")).toBeInTheDocument();
    expect(screen.getByText("Закупки")).toBeInTheDocument();
    expect(screen.getByText("HR")).toBeInTheDocument();
  });

  it("прячет модули, недоступные по allowedSlugs (RBAC)", async () => {
    render(<Sidebar allowedSlugs={["home", "crm"]} />);
    expect(await screen.findByText("CRM")).toBeInTheDocument();
    expect(screen.getByText("Главная")).toBeInTheDocument();
    expect(screen.queryByText("Закупки")).not.toBeInTheDocument();
    expect(screen.queryByText("HR")).not.toBeInTheDocument();
    expect(screen.queryByText("Склад")).not.toBeInTheDocument();
  });

  it("allowedSlugs=null (по умолчанию) показывает все модули", async () => {
    render(<Sidebar allowedSlugs={null} />);
    expect(await screen.findByText("CRM")).toBeInTheDocument();
    expect(screen.getByText("Закупки")).toBeInTheDocument();
    expect(screen.getByText("Юр. отдел")).toBeInTheDocument();
  });

  it("сворачивает и разворачивает rail по клику на тоггл", async () => {
    localStorage.setItem("aios-sidebar-collapsed", "0");
    render(<Sidebar />);
    const collapseBtn = await screen.findByLabelText("Свернуть меню");
    expect(screen.getByText("CRM")).toBeInTheDocument();

    fireEvent.click(collapseBtn);

    // После сворачивания подписи модулей исчезают из DOM (showFull=false),
    // а в rail появляется мини-тоггл "Раскрыть меню".
    await waitFor(() => expect(screen.queryByText("CRM")).not.toBeInTheDocument());
    const expandBtn = screen.getByLabelText("Раскрыть меню");
    expect(localStorage.getItem("aios-sidebar-collapsed")).toBe("1");

    fireEvent.click(expandBtn);
    expect(await screen.findByText("CRM")).toBeInTheDocument();
    expect(localStorage.getItem("aios-sidebar-collapsed")).toBe("0");
  });

  it("подсвечивает активный пункт подменю CRM (Лиды) на маршруте /crm/leads", async () => {
    mockUsePathname.mockReturnValue("/crm/leads");
    render(<Sidebar />);
    const leadsLink = (await screen.findByText("Лиды")).closest("a") as HTMLElement;
    expect(leadsLink.className).toContain("text-accent-ink");
    expect(leadsLink.className).toContain("font-medium");

    const dealsLink = screen.getByText("Сделки").closest("a") as HTMLElement;
    expect(dealsLink.className).not.toContain("text-accent-ink");
  });

  it("подсвечивает Маркетинг и вложенный SEO по префиксу вложенного маршрута", async () => {
    mockUsePathname.mockReturnValue("/erp/marketing/seo/details");
    render(<Sidebar />);
    // marketingActive => модуль раскрыт, показывает подпункты
    const seoLink = (await screen.findByText("SEO / GEO")).closest("a") as HTMLElement;
    expect(seoLink.className).toContain("text-accent-ink");

    const camps = screen.getByText("Кампании").closest("a") as HTMLElement;
    expect(camps.className).not.toContain("text-accent-ink");
    expect(camps.className).toContain("text-muted");
  });

  it("не подсвечивает вложенный подпункт по префиксу, когда путь короче (глубина <=2)", async () => {
    // На корне модуля "/erp/marketing" вложенный "SEO / GEO" (/erp/marketing/seo)
    // не должен считаться активным — префиксное правило требует depth>2 И реального
    // вложения (pathname.startsWith(href + "/")), а не совпадения по корню.
    mockUsePathname.mockReturnValue("/erp/marketing");
    render(<Sidebar />);
    const seo = (await screen.findByText("SEO / GEO")).closest("a") as HTMLElement;
    expect(seo.className).not.toContain("text-accent-ink");
    expect(seo.className).toContain("text-muted");
  });

  it("показывает профиль пользователя и роль, вызывает logout с очисткой сессии", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    render(<Sidebar userName="Иван Петров" roleTitle="Менеджер" />);
    expect(await screen.findByText("Иван Петров")).toBeInTheDocument();
    expect(screen.getByText("Менеджер")).toBeInTheDocument();

    const logoutBtn = screen.getByLabelText("Выйти");
    fireEvent.click(logoutBtn);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/auth/logout", { method: "POST" }));
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/login"));
    expect(mockRefresh).toHaveBeenCalled();
  });

  it("показывает «—» вместо роли, когда roleTitle не передан", async () => {
    render(<Sidebar userName="Анна" />);
    expect(await screen.findByText("Анна")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("считает инициалы из имени пользователя (первые буквы первых 2 слов)", async () => {
    render(<Sidebar userName="Иван Петров" />);
    // avatar — span с инициалами рядом с именем
    await screen.findByText("Иван Петров");
    expect(screen.getByText("ИП")).toBeInTheDocument();
  });

  it("в свёрнутом состоянии профиль показывает только аватар с title, без текста имени", async () => {
    localStorage.setItem("aios-sidebar-collapsed", "1");
    render(<Sidebar userName="Иван Петров" roleTitle="Менеджер" />);
    // Дожидаемся эффекта гидрации: rail остаётся свёрнутым.
    await waitFor(() => expect(screen.queryByText("CRM")).not.toBeInTheDocument());
    expect(screen.queryByText("Иван Петров")).not.toBeInTheDocument();
    expect(screen.queryByText("Менеджер")).not.toBeInTheDocument();
    const avatar = screen.getByTitle("Иван Петров");
    expect(avatar).toHaveTextContent("ИП");
  });

  it("переключает режим редактирования порядка модулей по клику на карандаш", async () => {
    localStorage.setItem("aios-sidebar-collapsed", "0");
    render(<Sidebar />);
    const editBtn = await screen.findByLabelText("Редактировать меню");
    fireEvent.click(editBtn);
    expect(await screen.findByLabelText("Готово")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Готово"));
    expect(await screen.findByLabelText("Редактировать меню")).toBeInTheDocument();
  });

  it("переименовывает логотип по клику + Enter и сохраняет в localStorage", async () => {
    localStorage.setItem("aios-sidebar-collapsed", "0");
    render(<Sidebar />);
    const logoBtn = await screen.findByTitle("Клик — переименовать");
    fireEvent.click(logoBtn);

    const input = screen.getByDisplayValue("ERP");
    fireEvent.change(input, { target: { value: "Компания" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("Компания")).toBeInTheDocument();
    expect(localStorage.getItem("aios-sidebar-logo")).toBe("Компания");
  });

  it("отменяет переименование логотипа по Escape, оставляя прежний текст", async () => {
    localStorage.setItem("aios-sidebar-collapsed", "0");
    render(<Sidebar />);
    const logoBtn = await screen.findByTitle("Клик — переименовать");
    fireEvent.click(logoBtn);

    const input = screen.getByDisplayValue("ERP");
    fireEvent.change(input, { target: { value: "Черновик" } });
    fireEvent.keyDown(input, { key: "Escape" });

    expect(await screen.findByText("ERP")).toBeInTheDocument();
    expect(screen.queryByText("Черновик")).not.toBeInTheDocument();
  });
});
