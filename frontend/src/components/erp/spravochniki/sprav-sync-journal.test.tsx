import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SpravSyncJournal } from "@/components/erp/spravochniki/sprav-sync-journal";
import type { SyncJournalEntry } from "@/lib/reference-data";

const entries: SyncJournalEntry[] = [
  {
    id: 1,
    entity_type: "counterparty",
    entity_id: 501,
    system: "1c",
    origin: "erp",
    direction: "out",
    state: "synced",
    external_ref: "CP-9001",
    last_synced_at: "2026-07-10 14:05:00.000000",
    error_text: null,
  },
  {
    id: 2,
    entity_type: "sku",
    entity_id: 77,
    system: "1c",
    origin: "erp",
    direction: "out",
    state: "pending",
    external_ref: null,
    last_synced_at: null,
    error_text: null,
  },
  {
    id: 3,
    entity_type: "counterparty",
    entity_id: 502,
    system: "1c",
    origin: "erp",
    direction: "out",
    state: "error",
    external_ref: null,
    last_synced_at: null,
    error_text: "1С отклонила: дубль УНП",
  },
];

describe("SpravSyncJournal", () => {
  it("рендерит пустое состояние без таблицы, когда записей нет", () => {
    render(<SpravSyncJournal entries={[]} />);

    expect(
      screen.getByText(/Очередь пуста — нет записей на выгрузку/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    // счётчики в шапке всё равно нулевые
    expect(screen.getByText("выгружено:").closest("span")).toHaveTextContent("выгружено: 0");
    expect(screen.getByText("в очереди:").closest("span")).toHaveTextContent("в очереди: 0");
    expect(screen.getByText("ошибок:").closest("span")).toHaveTextContent("ошибок: 0");
  });

  it("считает счётчики выгружено/в очереди/ошибок по состояниям записей", () => {
    render(<SpravSyncJournal entries={entries} />);

    expect(screen.getByText("выгружено:").closest("span")).toHaveTextContent("выгружено: 1");
    expect(screen.getByText("в очереди:").closest("span")).toHaveTextContent("в очереди: 1");
    expect(screen.getByText("ошибок:").closest("span")).toHaveTextContent("ошибок: 1");
  });

  it("рендерит строку synced: тип сущности, id, внешний ref и время в DD.MM.YYYY HH:MM", () => {
    render(<SpravSyncJournal entries={entries} />);

    const rows = screen.getAllByRole("row");
    // rows[0] — заголовок, rows[1] — первая запись (synced)
    const row = within(rows[1]);

    expect(row.getByText("Контрагент")).toBeInTheDocument();
    expect(row.getByText("#501")).toBeInTheDocument();
    expect(row.getByText("выгружено")).toBeInTheDocument();
    expect(row.getByText("CP-9001")).toBeInTheDocument();
    expect(row.getByText("10.07.2026 14:05")).toBeInTheDocument();
  });

  it("рендерит строку pending: номенклатура, статус «в очереди», прочерки вместо внешнего ref/времени", () => {
    render(<SpravSyncJournal entries={entries} />);

    const rows = screen.getAllByRole("row");
    const row = within(rows[2]);

    expect(row.getByText("Номенклатура")).toBeInTheDocument();
    expect(row.getByText("#77")).toBeInTheDocument();
    expect(row.getByText("в очереди")).toBeInTheDocument();
    const dashes = row.getAllByText("—");
    expect(dashes).toHaveLength(2);
  });

  it("рендерит строку error: статус «ошибка» и текст ошибки", () => {
    render(<SpravSyncJournal entries={entries} />);

    const rows = screen.getAllByRole("row");
    const row = within(rows[3]);

    expect(row.getByText("ошибка")).toBeInTheDocument();
    expect(row.getByText("1С отклонила: дубль УНП")).toBeInTheDocument();
  });

  it("рендерит все три строки таблицы для трёх записей", () => {
    render(<SpravSyncJournal entries={entries} />);

    const rows = screen.getAllByRole("row");
    // 1 заголовок + 3 записи
    expect(rows).toHaveLength(4);
  });
});
