import { fireEvent, render, screen } from "@testing-library/react";
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
vi.mock("next/navigation", () => ({
  usePathname: () => "/crm/deals",
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
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

  it("прячет модули вне allowedSlugs, оставляя разрешённые", async () => {
    render(<Sidebar allowedSlugs={["home", "crm"]} />);
    // разрешённые видны
    expect(await screen.findByText("CRM")).toBeInTheDocument();
    expect(screen.getByText("Главная")).toBeInTheDocument();
    // всё, чего нет в списке, отфильтровано
    expect(screen.queryByText("Закупки")).not.toBeInTheDocument();
    expect(screen.queryByText("HR")).not.toBeInTheDocument();
    expect(screen.queryByText("Финансы")).not.toBeInTheDocument();
  });

  it("показывает профиль сотрудника с инициалами, ролью и кнопкой выхода", async () => {
    render(<Sidebar userName="Иван Петров" roleTitle="РОП" />);
    expect(await screen.findByText("Иван Петров")).toBeInTheDocument();
    expect(screen.getByText("РОП")).toBeInTheDocument();
    // initials(): первые буквы двух слов
    expect(screen.getByText("ИП")).toBeInTheDocument();
    expect(screen.getByLabelText("Выйти")).toBeInTheDocument();
  });

  it("без userName не рендерит блок профиля и кнопку выхода", async () => {
    render(<Sidebar />);
    await screen.findByText("CRM");
    expect(screen.queryByLabelText("Выйти")).not.toBeInTheDocument();
  });

  it("initials() чистит кавычки/точки в имени и берёт первые буквы", async () => {
    render(<Sidebar userName="ООО «Ромашка»" />);
    // «» и прочая пунктуация заменяются пробелом → слова ["ООО","Ромашка"] → "ОР"
    expect(await screen.findByText("ОР")).toBeInTheDocument();
  });

  it("выделяет активный подраздел (Сделки) accent-стилем, неактивный — muted", async () => {
    render(<Sidebar />);
    const active = (await screen.findByText("Сделки")).closest("a");
    const inactive = screen.getByText("Лиды").closest("a");
    expect(active?.className).toContain("text-accent-ink");
    expect(inactive?.className).toContain("text-muted");
  });

  it("сворачивает меню по кнопке — подписи модулей исчезают", async () => {
    render(<Sidebar />);
    expect(await screen.findByText("CRM")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Свернуть меню"));
    // showFull=false → span-подписи не рендерятся
    expect(screen.queryByText("CRM")).not.toBeInTheDocument();
    expect(screen.queryByText("Сделки")).not.toBeInTheDocument();
    // появляется мини-тоггл раскрытия
    expect(screen.getByLabelText("Раскрыть меню")).toBeInTheDocument();
  });

  it("в режиме правки ссылки модулей превращаются в неактивные строки", async () => {
    render(<Sidebar />);
    // до правки «Закупки» — ссылка
    expect((await screen.findByText("Закупки")).closest("a")).not.toBeNull();
    fireEvent.click(screen.getByLabelText("Редактировать меню"));
    // кнопка переключилась в «Готово»
    expect(screen.getByLabelText("Готово")).toBeInTheDocument();
    // в edit-режиме строка перестаёт быть <a> (draggable div)
    expect(screen.getByText("Закупки").closest("a")).toBeNull();
  });

  it("редактирование логотипа: Enter сохраняет новый текст в localStorage", async () => {
    render(<Sidebar />);
    fireEvent.click(await screen.findByText("ERP"));
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Моя" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("Моя")).toBeInTheDocument();
    expect(localStorage.getItem("aios-sidebar-logo")).toBe("Моя");
  });

  it("редактирование логотипа: Escape отменяет и НЕ пишет в localStorage", async () => {
    render(<Sidebar />);
    fireEvent.click(await screen.findByText("ERP"));
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "XXX" } });
    fireEvent.keyDown(input, { key: "Escape" });
    // текст логотипа не изменился, запись не выполнена
    expect(screen.getByText("ERP")).toBeInTheDocument();
    expect(localStorage.getItem("aios-sidebar-logo")).toBeNull();
  });

  it("пустой логотип откатывается к «ERP» по фолбэку", async () => {
    render(<Sidebar />);
    fireEvent.click(await screen.findByText("ERP"));
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("ERP")).toBeInTheDocument();
    expect(localStorage.getItem("aios-sidebar-logo")).toBe("ERP");
  });

  it("выход дергает эндпоинт разлогина", async () => {
    const fetchMock = vi.fn(() => Promise.resolve({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Sidebar userName="Иван Петров" />);
    fireEvent.click(await screen.findByLabelText("Выйти"));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/logout",
      expect.objectContaining({ method: "POST" }),
    );
    vi.unstubAllGlobals();
  });
});
