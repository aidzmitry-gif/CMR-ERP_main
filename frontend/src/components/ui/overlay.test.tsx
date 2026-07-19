import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Drawer, Modal, Tabs, Tooltip } from "@/components/ui/overlay";

describe("Tabs", () => {
  const tabs = [
    { label: "Первая", content: <div>Контент первой</div> },
    { label: "Вторая", content: <div>Контент второй</div> },
  ];

  it("рендерит первую вкладку активной по умолчанию", () => {
    render(<Tabs tabs={tabs} />);
    expect(screen.getByText("Первая").className).toContain("bg-accent");
    expect(screen.getByText("Вторая").className).not.toContain("bg-accent");
    expect(screen.getByText("Контент первой")).toBeInTheDocument();
  });

  it("уважает initial при выборе стартовой вкладки", () => {
    render(<Tabs tabs={tabs} initial={1} />);
    expect(screen.getByText("Вторая").className).toContain("bg-accent");
    expect(screen.getByText("Контент второй")).toBeInTheDocument();
  });

  it("переключает активную вкладку и её контент по клику", () => {
    render(<Tabs tabs={tabs} />);
    fireEvent.click(screen.getByText("Вторая"));
    expect(screen.getByText("Вторая").className).toContain("bg-accent");
    expect(screen.getByText("Первая").className).not.toContain("bg-accent");
    expect(screen.getByText("Контент второй")).toBeInTheDocument();
    expect(screen.queryByText("Контент первой")).not.toBeInTheDocument();
  });

  it("не рендерит блок контента, если у вкладки его нет", () => {
    const { container } = render(<Tabs tabs={[{ label: "Пусто" }]} />);
    expect(container.querySelector(".mt-4")).toBeNull();
  });
});

describe("Modal", () => {
  it("не рендерит ничего, если open=false", () => {
    const { container } = render(
      <Modal open={false} onClose={() => {}} title="Заголовок">
        Тело
      </Modal>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("рендерит заголовок, детей и футер при open=true", () => {
    render(
      <Modal open onClose={() => {}} title="Заголовок" footer={<button>Сохранить</button>}>
        Тело окна
      </Modal>,
    );
    expect(screen.getByText("Заголовок")).toBeInTheDocument();
    expect(screen.getByText("Тело окна")).toBeInTheDocument();
    expect(screen.getByText("Сохранить")).toBeInTheDocument();
  });

  it("вызывает onClose при клике на фон и на кнопку закрытия", () => {
    const onClose = vi.fn();
    const { container } = render(
      <Modal open onClose={onClose} title="Т">
        Тело
      </Modal>,
    );
    const overlay = container.firstChild as HTMLElement;
    fireEvent.click(overlay);
    expect(onClose).toHaveBeenCalledTimes(1);

    const closeBtn = overlay.querySelector("button") as HTMLElement;
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("не вызывает onClose при клике внутри содержимого окна", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Т">
        <span>Внутренний текст</span>
      </Modal>,
    );
    fireEvent.click(screen.getByText("Внутренний текст"));
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("Drawer", () => {
  it("применяет открытые классы прозрачности/сдвига при open=true", () => {
    const { container } = render(
      <Drawer open onClose={() => {}} title="Заголовок">
        Тело
      </Drawer>,
    );
    const backdrop = container.querySelector(".absolute.inset-0") as HTMLElement;
    expect(backdrop.className).toContain("opacity-100");
    const panel = container.querySelector(".absolute.right-0") as HTMLElement;
    expect(panel.className).toContain("translate-x-0");
  });

  it("применяет закрытые классы (сдвиг за экран, pointer-events-none) при open=false", () => {
    const { container } = render(
      <Drawer open={false} onClose={() => {}} title="Заголовок">
        Тело
      </Drawer>,
    );
    const root = container.firstChild as HTMLElement;
    expect(root.className).toContain("pointer-events-none");
    const backdrop = container.querySelector(".absolute.inset-0") as HTMLElement;
    expect(backdrop.className).toContain("opacity-0");
    const panel = container.querySelector(".absolute.right-0") as HTMLElement;
    expect(panel.className).toContain("translate-x-full");
  });

  it("вызывает onClose при клике на фон и на кнопку закрытия", () => {
    const onClose = vi.fn();
    const { container } = render(
      <Drawer open onClose={onClose} title="Заголовок">
        Содержимое
      </Drawer>,
    );
    const backdrop = container.querySelector(".absolute.inset-0") as HTMLElement;
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);

    const closeBtn = container.querySelector(".absolute.right-0 button") as HTMLElement;
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("рендерит переданных детей и заголовок", () => {
    render(
      <Drawer open onClose={() => {}} title="Карточка сделки">
        <div>Детали сделки</div>
      </Drawer>,
    );
    expect(screen.getByText("Карточка сделки")).toBeInTheDocument();
    expect(screen.getByText("Детали сделки")).toBeInTheDocument();
  });
});

describe("Tooltip", () => {
  it("рендерит текст подсказки и переданных детей", () => {
    render(
      <Tooltip text="Подсказка">
        <span>Наведи</span>
      </Tooltip>,
    );
    expect(screen.getByText("Наведи")).toBeInTheDocument();
    expect(screen.getByText("Подсказка")).toBeInTheDocument();
  });

  it("скрывает текст подсказки по умолчанию через opacity-0", () => {
    render(
      <Tooltip text="Скрытый текст">
        <span>Триггер</span>
      </Tooltip>,
    );
    expect(screen.getByText("Скрытый текст").className).toContain("opacity-0");
  });
});
