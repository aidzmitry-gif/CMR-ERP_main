import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Единственная I/O-зависимость экрана — структурный запрос к бэкенду.
// buildQueryInput/FALLBACK_CATALOG из @/lib/spravochniki-ai — чистые, НЕ мокаем
// (проверяем реальную сборку/тримминг параметров запроса).
vi.mock("@/lib/reference-data", () => ({ runReferenceQuery: vi.fn() }));

import { SpravAi } from "@/components/erp/spravochniki/sprav-ai";
import type { AiCatalog } from "@/lib/reference-data";
import { runReferenceQuery } from "@/lib/reference-data";

const mockQuery = runReferenceQuery as ReturnType<typeof vi.fn>;

// Детерминированный каталог: первый ref — не версионный (дефолт селекта),
// второй — версионный (SCD2) для проверки историчной ветки.
const catalog: AiCatalog = {
  tool: {
    name: "reference.query",
    endpoint: "/system/references/query",
    params: ["ref", "key", "as_of", "name", "limit"],
    note: "Структурный SQL-запрос с учётом историчности.",
  },
  references: [
    {
      key: "core.counterparties",
      title: "Контрагенты",
      endpoint: "/refs/counterparties",
      owner_schema: "public",
      versioned: false,
      columns: [{ name: "unp", type: "string", semantic: "counterparty.tax_id" }],
      description: "Эталонные карточки клиентов.",
    },
    {
      key: "core.vat_rates",
      title: "Ставки НДС",
      endpoint: "/refs/vat-rates",
      owner_schema: "public",
      versioned: true,
      columns: [{ name: "rate", type: "number", semantic: "vat.rate" }],
      description: "Ставка на дату документа.",
    },
  ],
};

beforeEach(() => vi.clearAllMocks());

describe("SpravAi", () => {
  it("режим данных: рендерит справочники каталога, инструмент и note без бейджа «демо»", () => {
    render(<SpravAi initial={catalog} />);

    // справочники из переданного каталога (кнопка-карточка + опция селекта)
    expect(screen.getAllByText("Контрагенты").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Ставки НДС").length).toBeGreaterThan(0);
    // имя инструмента и его пояснение
    expect(screen.getByText("reference.query")).toBeInTheDocument();
    expect(screen.getByText("Структурный SQL-запрос с учётом историчности.")).toBeInTheDocument();
    // бэкенд доступен → нет плашки «демо»
    expect(screen.queryByText("демо")).not.toBeInTheDocument();
    expect(screen.queryByText(/бэкенд недоступен/i)).not.toBeInTheDocument();
  });

  it("демо-режим (initial=null): бейдж «демо», плашка недоступности и fallback-каталог", () => {
    render(<SpravAi initial={null} />);

    expect(screen.getAllByText("демо").length).toBeGreaterThan(0);
    expect(screen.getByText(/бэкенд недоступен/i)).toBeInTheDocument();
    // fallback-каталог реально подставлен — виден справочник из FALLBACK_CATALOG
    expect(screen.getAllByText("Контрагенты").length).toBeGreaterThan(0);
    expect(screen.getByText("🤖 ai_exposed")).toBeInTheDocument();
  });

  it("пустой каталог: показывает подсказку об отсутствии справочников", () => {
    render(<SpravAi initial={{ ...catalog, references: [] }} />);
    expect(screen.getByText("Нет доступных справочников")).toBeInTheDocument();
  });

  it("выбор версионного справочника открывает SCD2-ветку (метка as_of и колонки меняются)", () => {
    render(<SpravAi initial={catalog} />);

    // дефолт — первый (не версионный) справочник: SCD2-метки у as_of нет,
    // а в подсказке колонок — колонка контрагентов.
    expect(screen.queryByText("(SCD2)")).not.toBeInTheDocument();
    expect(screen.getByText(/unp: string/)).toBeInTheDocument();

    // клик по карточке версионного справочника
    fireEvent.click(screen.getByRole("button", { name: /Ставки НДС/ }));

    // историчная ветка включилась: метка (SCD2) у as_of + колонки версионного ref
    expect(screen.getByText("(SCD2)")).toBeInTheDocument();
    expect(screen.getByText(/rate: number/)).toBeInTheDocument();
    expect(screen.queryByText(/unp: string/)).not.toBeInTheDocument();
  });

  it("отправка формы собирает параметры (тримминг пустых) и зовёт runReferenceQuery", async () => {
    mockQuery.mockResolvedValue({ ref: "core.counterparties", result: [] });
    render(<SpravAi initial={catalog} />);

    fireEvent.change(screen.getByPlaceholderText("напр. USD, НДС"), { target: { value: "  USD " } });
    fireEvent.change(screen.getByPlaceholderText("напр. Ромашка"), { target: { value: "Ромашка" } });
    fireEvent.change(screen.getByPlaceholderText("10"), { target: { value: "5" } });

    fireEvent.click(screen.getByRole("button", { name: "Выполнить запрос" }));

    await waitFor(() =>
      expect(mockQuery).toHaveBeenCalledWith({
        ref: "core.counterparties",
        key: "USD",
        name: "Ромашка",
        limit: 5,
      }),
    );
  });

  it("успешный запрос показывает результат: ref/key/на дату и JSON тела", async () => {
    mockQuery.mockResolvedValue({
      ref: "core.vat_rates",
      key: "НДС20",
      as_of: "2026-01-01",
      result: { rate: 20 },
    });
    render(<SpravAi initial={catalog} />);

    fireEvent.click(screen.getByRole("button", { name: "Выполнить запрос" }));

    expect(await screen.findByText("ref: core.vat_rates")).toBeInTheDocument();
    expect(screen.getByText("key: НДС20")).toBeInTheDocument();
    expect(screen.getByText("на дату 2026-01-01")).toBeInTheDocument();
    // тело результата отрисовано как форматированный JSON
    expect(screen.getByText(/"rate": 20/)).toBeInTheDocument();
  });

  it("сбой запроса (null) показывает ошибку, а не молча пустоту", async () => {
    mockQuery.mockResolvedValue(null);
    render(<SpravAi initial={catalog} />);

    fireEvent.click(screen.getByRole("button", { name: "Выполнить запрос" }));

    expect(await screen.findByText(/Бэкенд недоступен или вернул ошибку/)).toBeInTheDocument();
    // результата нет — блок ref не отрисован
    expect(screen.queryByText(/^ref: /)).not.toBeInTheDocument();
  });

  it("во время запроса кнопка заблокирована, после ответа — снова активна", async () => {
    let resolve!: (v: unknown) => void;
    mockQuery.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<SpravAi initial={catalog} />);

    const btn = screen.getByRole("button", { name: "Выполнить запрос" });
    fireEvent.click(btn);

    // запрос «висит» → кнопка disabled (loading-ветка)
    await waitFor(() => expect(btn).toBeDisabled());

    resolve({ ref: "core.counterparties", result: [] });
    await waitFor(() => expect(btn).not.toBeDisabled());
  });
});
