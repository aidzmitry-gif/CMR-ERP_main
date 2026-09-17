import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import BoardDemoPage from "@/app/design/board/page";
import ChartsDemoPage from "@/app/design/charts/page";
import ComponentsPage from "@/app/design/components/page";
import DealCardDemoPage from "@/app/design/deal-card/page";
import FullIndexPage from "@/app/design/full/page";
import { FullDealCard, FullKanban, FullRop } from "@/app/design/full/themed-screens";
import RopDemoPage from "@/app/design/rop/page";
import ThemesGalleryPage from "@/app/design/themes/page";

describe("design-demo pages", () => {
  it("рендерит графики, галерею тем и полноразмерные экраны", () => {
    const { rerender } = render(<ChartsDemoPage />);
    expect(screen.getByText("Как будут выглядеть графики")).toBeInTheDocument();
    expect(screen.getByText("Динамика выручки и маржи")).toBeInTheDocument();

    rerender(<ThemesGalleryPage />);
    expect(screen.getByText("Сравните дизайн-решения")).toBeInTheDocument();
    expect(screen.getByText("A · Stripe / Notion")).toBeInTheDocument();
    expect(screen.getByText("F · High-contrast bold")).toBeInTheDocument();

    rerender(
      <>
        <FullIndexPage />
        <FullDealCard />
        <FullKanban />
        <FullRop />
      </>,
    );
    expect(screen.getByText("6 стилей × 3 экрана")).toBeInTheDocument();
    expect(screen.getByText("ООО «БелТранс» — поставка АКБ")).toBeInTheDocument();
    expect(screen.getByText("Квалификация")).toBeInTheDocument();
    expect(screen.getByText("Обзор РОП — июнь 2026")).toBeInTheDocument();
  });

  it("рендерит demo-страницы доски, карточки и РОП", () => {
    const { rerender } = render(<BoardDemoPage />);
    expect(screen.getByText(/Демо · доска сделок/)).toBeInTheDocument();
    rerender(<DealCardDemoPage />);
    expect(screen.getByText(/Демо · полная карточка сделки/)).toBeInTheDocument();
    rerender(<RopDemoPage />);
    expect(screen.getByText(/Демо · РОП на новых примитивах/)).toBeInTheDocument();
  });

  it("показывает и закрывает интерактивные modal/drawer из каталога компонентов", () => {
    render(<ComponentsPage />);
    fireEvent.click(screen.getByRole("button", { name: "Открыть модалку" }));
    expect(screen.getByText("Создать сделку")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByText("Создать сделку")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Открыть drawer" }));
    expect(screen.getByText("CRM-1029 · ООО «БелТранс»")).toBeInTheDocument();
  });
});
