import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

// Компонент — чистый client-component на demo-данных: нет @/lib/api, нет next/navigation.
// Хелперы @/lib/format НЕ мокаем — пусть считают по-настоящему, ими же строим ожидаемые строки.
import { MarginByMonth } from "@/components/margin/margin-by-month";
import { formatByn } from "@/lib/format";

// formatByn разделяет разряды NBSP (U+00A0); дефолтный нормализатор RTL схлопывает его
// в обычный пробел — приводим ожидаемую строку к тому же виду, иначе getByText не найдёт.
const byn = (n: number) => formatByn(n).replace(/ /g, " ");

// Итоги режима «Все (отдел)», вычисленные из demo-данных компонента вручную —
// чтобы тест ловил регресс арифметики, а не повторял её.
// Июнь: rev 186 000, gp 63 200 (22 800+22 400+18 000), маржа 34%.
// Июль: rev 198 000, gp 71 500, цель 70 000 → перевыполнение +1 500.
// Годовая шапка: планВперёд = Σ gp всех месяцев = 193 000, факт 280 000, осталось 287 000.

describe("MarginByMonth", () => {
  it("рендерит заголовок и годовую цель валовой прибыли (760 000 BYN)", () => {
    render(<MarginByMonth />);
    expect(
      screen.getByRole("heading", { name: "План валовой прибыли по месяцам" }),
    ).toBeInTheDocument();
    // большое число годовой цели — уникальный узел
    expect(screen.getByText(byn(760_000))).toBeInTheDocument();
  });

  it("годовая шапка декомпозирует цель на факт / план вперёд / остаток с процентами", () => {
    render(<MarginByMonth />);
    // Факт (янв–май) 280 000 = 37% годовой цели
    const fakt = screen.getByText(/Факт \(янв–май\)/).closest("span") as HTMLElement;
    expect(within(fakt).getByText(byn(280_000))).toBeInTheDocument();
    expect(within(fakt).getByText("37%")).toBeInTheDocument();

    // План вперёд (июнь+) = сумма плановой прибыли месяцев = 193 000 = 25%
    const plan = screen.getByText(/План вперёд/).closest("span") as HTMLElement;
    expect(within(plan).getByText(byn(193_000))).toBeInTheDocument();
    expect(within(plan).getByText("25%")).toBeInTheDocument();

    // Осталось до годовой цели = 760 000 − 280 000 − 193 000 = 287 000 = 38%
    const gap = screen.getByText(/Осталось до годовой цели/).closest("span") as HTMLElement;
    expect(within(gap).getByText(byn(287_000))).toBeInTheDocument();
    expect(within(gap).getByText("38%")).toBeInTheDocument();
  });

  it("режим «Все»: KPI-плитка Июня показывает валовую прибыль 63 200 и маржу 34%", () => {
    render(<MarginByMonth />);
    // gp Июня в режиме отдела — встречается в плитке и в шапке колонки
    expect(screen.getAllByText(byn(63_200)).length).toBeGreaterThan(0);
    expect(screen.getByText(/маржа 34% · выручка/)).toBeInTheDocument();
  });

  it("режим «Все»: недобор до цели месяца vs перевыполнение считаются по знаку diff", () => {
    render(<MarginByMonth />);
    // Единственный месяц с перевыполнением — Июль (gp 71 500 > цель 70 000 → +1 500).
    // Число слито в один текст-узел со словами, поэтому проверяем через textContent (сохраняет NBSP).
    const over = screen.getByText(/цель достигнута · \+/);
    expect(over.textContent).toContain(formatByn(1_500));
    // Остальные три месяца (Июнь −6 800, Август, Сентябрь) недобирают → «добрать …».
    // /добрать/ не задевает loadLabel «добирать» (другое слово).
    expect(screen.getAllByText(/добрать/)).toHaveLength(3);
  });

  it("фильтр по менеджеру пересчитывает итоги: Июнь Сидорова = 40 800, а не 63 200", () => {
    render(<MarginByMonth />);
    // до фильтра — отдельский итог Июня виден
    expect(screen.getAllByText(byn(63_200)).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Сидоров К." }));

    // после фильтра Июнь = рейсы Сидорова (22 800 + 18 000) = 40 800; отдельский 63 200 исчез
    expect(screen.getAllByText(byn(40_800)).length).toBeGreaterThan(0);
    expect(screen.queryByText(byn(63_200))).not.toBeInTheDocument();
  });

  it("активная кнопка менеджера подсвечивается (bg-accent-soft) после клика", () => {
    render(<MarginByMonth />);
    const btn = screen.getByRole("button", { name: "Сидоров К." });
    expect(btn.className).not.toMatch(/bg-accent-soft/);
    fireEvent.click(btn);
    expect(btn.className).toMatch(/bg-accent-soft/);
    // «Все (отдел)» больше не активна
    expect(screen.getByRole("button", { name: "Все (отдел)" }).className).not.toMatch(
      /bg-accent-soft/,
    );
  });

  it("под выбранным менеджером пустой месяц (общий прогноз) показывает заглушку и «вклад в цель»", () => {
    render(<MarginByMonth />);
    // в режиме «Все» заглушки нет, есть строка про цель месяца
    expect(screen.queryByText("Нет рейсов этого менеджера")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Сидоров К." }));

    // Сентябрь+ — только общий прогноз (mgr=all) → под менеджером колонка пуста
    expect(screen.getByText("Нет рейсов этого менеджера")).toBeInTheDocument();
    // футер плиток переключился с «цель …» на «вклад в цель:»
    expect(screen.getAllByText(/вклад в цель:/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/цель достигнута/)).not.toBeInTheDocument();
  });
});
