import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: refreshMock }) }));
vi.mock("@/lib/reference-data", () => ({ mergeCounterparties: vi.fn(), totalDuplicates: vi.fn() }));

import { SpravMerge } from "@/components/erp/spravochniki/sprav-merge";
import { mergeCounterparties, totalDuplicates, type DuplicateCluster } from "@/lib/reference-data";

const mergeMock = mergeCounterparties as ReturnType<typeof vi.fn>;
const totalMock = totalDuplicates as ReturnType<typeof vi.fn>;

const clusterA: DuplicateCluster = {
  unp: "100200300",
  members: [
    { id: 1, name: "ООО Ромашка" },
    { id: 2, name: "ООО Ромашка (дубль)" },
    { id: 3, name: "ООО Ромашка (дубль 2)" },
  ],
};

const clusterB: DuplicateCluster = {
  unp: "500600700",
  members: [
    { id: 10, name: "ЧУП Василёк" },
    { id: 11, name: "ЧУП Василёк (дубль)" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  totalMock.mockReturnValue(5);
});

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("SpravMerge", () => {
  it("пустой список кластеров → честная заглушка «Дублей не обнаружено»", () => {
    render(<SpravMerge initial={[]} />);
    expect(screen.getByText("Дублей не обнаружено.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("первый кластер выбран по умолчанию: эталон, дубли и счётчик очереди", () => {
    render(<SpravMerge initial={[clusterA, clusterB]} />);

    // счётчик очереди — из totalDuplicates(initial)
    expect(screen.getByText("Кандидаты на слияние (5)")).toBeInTheDocument();

    // заголовок разбора кластера — первый (clusterA), эталон = members[0]
    expect(screen.getByText("Разбор кластера · УНП 100200300")).toBeInTheDocument();
    expect(screen.getAllByText("ООО Ромашка").length).toBeGreaterThan(0);

    // в карточке кластера показано число дублей (members.length - 1 = 2)
    expect(screen.getByText("2 дубл.")).toBeInTheDocument();
    // в карточке второго кластера — 1 дубль
    expect(screen.getByText("1 дубл.")).toBeInTheDocument();

    // ID контрагентов форматируются как CP-000001 и т.д. (встречаются и в карточке кластера, и в таблице разбора)
    expect(screen.getAllByText("CP-000001").length).toBeGreaterThan(0);
    expect(screen.getAllByText("CP-000002").length).toBeGreaterThan(0);
    expect(screen.getAllByText("CP-000003").length).toBeGreaterThan(0);
  });

  it("клик по карточке другого кластера переключает разбор", () => {
    render(<SpravMerge initial={[clusterA, clusterB]} />);

    const buttons = screen.getAllByRole("button", { name: "Разобрать" });
    fireEvent.click(buttons[1]); // выбрать clusterB

    expect(screen.getByText("Разбор кластера · УНП 500600700")).toBeInTheDocument();
    expect(screen.getAllByText("ЧУП Василёк").length).toBeGreaterThan(0);
    expect(screen.queryByText("Разбор кластера · УНП 100200300")).not.toBeInTheDocument();
  });

  it("кнопка «Слить» вызывает mergeCounterparties(survivorId, dupId) и router.refresh() после резолва", async () => {
    const d = deferred<boolean>();
    mergeMock.mockReturnValue(d.promise);

    render(<SpravMerge initial={[clusterA]} />);

    const mergeButtons = screen.getAllByRole("button", { name: /Слить/ });
    // survivor id=1, первый дубль id=2
    fireEvent.click(mergeButtons[0]);

    expect(mergeMock).toHaveBeenCalledWith(1, 2);
    // кнопка блокируется, пока запрос busy
    expect(mergeButtons[0]).toBeDisabled();

    d.resolve(true);
    await d.promise;
    expect(refreshMock).toHaveBeenCalled();
  });

  it("эталон помечен бейджем «★ эталон», дубли — бейджем «дубль», у эталона нет кнопки «Слить»", () => {
    render(<SpravMerge initial={[clusterA]} />);

    expect(screen.getByText("★ эталон")).toBeInTheDocument();
    expect(screen.getAllByText("дубль").length).toBe(2);

    // кнопок «Слить» ровно 2 (по числу дублей), не 3 (эталон без кнопки)
    expect(screen.getAllByRole("button", { name: /Слить/ }).length).toBe(2);
  });
});
