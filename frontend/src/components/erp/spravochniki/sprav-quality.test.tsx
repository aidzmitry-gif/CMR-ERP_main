import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// next/link → простая <a> в jsdom (ссылка на дедупликацию в детализации дублей).
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Мокаем ТОЛЬКО сетевой fetchQualityDetail (клиентский вызов при раскрытии строки);
// чистые qualityTone/типы остаются настоящими — цвет score-бейджа считает реальная логика.
vi.mock("@/lib/reference-data", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/reference-data")>();
  return { ...actual, fetchQualityDetail: vi.fn() };
});

import { SpravQuality } from "@/components/erp/spravochniki/sprav-quality";
import {
  fetchQualityDetail,
  type QualityDetail,
  type QualitySummaryRow,
} from "@/lib/reference-data";

const detailMock = fetchQualityDetail as ReturnType<typeof vi.fn>;

/** Отложенный промис — чтобы поймать состояние «loading» до резолва. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const skus: QualitySummaryRow = {
  ref: "core.skus",
  title: "Номенклатура",
  total: 100,
  score: 0.72, // < 0.8 → тон bad; < 0.95 → «требует внимания»
  issues_count: 3,
  by_kind: { missing: 5, duplicate: 0, broken_ref: 2, orphan: 0, margin_blind: 4 },
};

const counterparties: QualitySummaryRow = {
  ref: "core.counterparties",
  title: "Контрагенты",
  total: 50,
  score: 0.98, // >= 0.95 → тон ok, не в «worst»
  issues_count: 3,
  by_kind: { missing: 0, duplicate: 3, broken_ref: 0, orphan: 0 },
};

beforeEach(() => detailMock.mockReset());
afterEach(() => vi.clearAllMocks());

describe("SpravQuality", () => {
  it("пустая сводка → честная заглушка, без таблицы", () => {
    render(<SpravQuality summary={[]} />);
    expect(screen.getByText("Аудит качества недоступен")).toBeInTheDocument();
    expect(screen.getByText(/Данные не выдумываем/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("рисует строки: заголовок, ref, total, score-% и разбивку по видам", () => {
    render(<SpravQuality summary={[skus, counterparties]} />);

    expect(screen.getByText("Номенклатура")).toBeInTheDocument();
    expect(screen.getByText("core.skus")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();

    // score → проценты (реальный Math.round(score*100))
    expect(screen.getByText("72%")).toBeInTheDocument();
    expect(screen.getByText("98%")).toBeInTheDocument();

    // разбивка: missing=5 показан, duplicate=0 → прочерк «—»
    expect(screen.getByText("5")).toBeInTheDocument();
    const skusRow = screen.getByText("Номенклатура").closest("tr") as HTMLElement;
    expect(within(skusRow).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("тон score-бейджа отражает качество: плохой — красный, хороший — зелёный", () => {
    render(<SpravQuality summary={[skus, counterparties]} />);
    expect(screen.getByText("72%").className).toMatch(/red/);
    expect(screen.getByText("98%").className).toMatch(/emerald/);
  });

  it("шапка считает «требуют внимания» (score<0.95) и сумму маржа-слепых SKU", () => {
    render(<SpravQuality summary={[skus, counterparties]} />);
    // worst = только Номенклатура (0.72), Контрагенты (0.98) не в счёте
    expect(screen.getByText(/требуют внимания: 1/)).toBeInTheDocument();
    expect(screen.getByText(/маржа-слепых SKU: 4/)).toBeInTheDocument();
  });

  it("чистая сводка — оба индикатора шапки скрыты", () => {
    const clean: QualitySummaryRow = {
      ...counterparties,
      by_kind: { missing: 0, duplicate: 0, broken_ref: 0, orphan: 0 },
    };
    render(<SpravQuality summary={[clean]} />);
    expect(screen.queryByText(/требуют внимания/)).not.toBeInTheDocument();
    expect(screen.queryByText(/маржа-слепых SKU/)).not.toBeInTheDocument();
  });

  it("клик по строке грузит детализацию: сначала «Загрузка…», потом проблемы", async () => {
    const d = deferred<QualityDetail | null>();
    detailMock.mockReturnValue(d.promise);

    render(<SpravQuality summary={[skus, counterparties]} />);
    fireEvent.click(screen.getByText("Номенклатура"));

    // запрос ушёл именно по ключу раскрытой строки, показан индикатор загрузки
    expect(detailMock).toHaveBeenCalledWith("core.skus");
    expect(screen.getByText(/Загрузка детализации/)).toBeInTheDocument();

    d.resolve({
      ref: "core.skus",
      title: "Номенклатура",
      total: 100,
      score: 0.72,
      issues: [
        { kind: "missing", field: "tnved", count: 4, sample_keys: ["АКБ-1", "АКБ-2"] },
      ],
    });

    // KIND_LABEL «missing» → «Пропуски», поле и примеры отрисованы
    expect(await screen.findByText("Пропуски")).toBeInTheDocument();
    expect(screen.getByText("tnved")).toBeInTheDocument();
    expect(screen.getByText(/примеры: АКБ-1, АКБ-2/)).toBeInTheDocument();
    expect(screen.queryByText(/Загрузка детализации/)).not.toBeInTheDocument();
  });

  it("ошибка загрузки детализации (null) → сообщение об ошибке, не молча", async () => {
    detailMock.mockResolvedValue(null);
    render(<SpravQuality summary={[skus]} />);
    fireEvent.click(screen.getByText("Номенклатура"));
    expect(await screen.findByText(/Не удалось загрузить детализацию/)).toBeInTheDocument();
  });

  it("детализация без проблем → «справочник чист»", async () => {
    detailMock.mockResolvedValue({
      ref: "core.skus",
      title: "Номенклатура",
      total: 100,
      score: 1,
      issues: [],
    });
    render(<SpravQuality summary={[skus]} />);
    fireEvent.click(screen.getByText("Номенклатура"));
    expect(await screen.findByText(/справочник чист/)).toBeInTheDocument();
  });

  it("ссылка на дедупликацию — только у дублей контрагентов", async () => {
    detailMock.mockResolvedValue({
      ref: "core.counterparties",
      title: "Контрагенты",
      total: 50,
      score: 0.98,
      issues: [
        { kind: "duplicate", field: "unp", count: 3, sample_keys: ["УНП-1"] },
      ],
    });
    render(<SpravQuality summary={[counterparties]} />);
    fireEvent.click(screen.getByText("Контрагенты"));

    const link = await screen.findByRole("link", { name: /дедупликация/ });
    expect(link).toHaveAttribute("href", "/erp/spravochniki/merge");
  });

  it("повторный клик по строке сворачивает детализацию", async () => {
    detailMock.mockResolvedValue({
      ref: "core.skus",
      title: "Номенклатура",
      total: 100,
      score: 0.72,
      issues: [{ kind: "broken_ref", field: "group_id", count: 1, sample_keys: [] }],
    });
    render(<SpravQuality summary={[skus]} />);

    fireEvent.click(screen.getByText("Номенклатура"));
    // «Битые ссылки» — метка вида (в шапке столбец назван «Битые», не совпадает)
    expect(await screen.findByText("Битые ссылки")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Номенклатура"));
    expect(screen.queryByText("Битые ссылки")).not.toBeInTheDocument();
  });
});
