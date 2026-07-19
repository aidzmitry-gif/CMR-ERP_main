import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SpravMergeRules } from "@/components/erp/spravochniki/sprav-merge-rules";
import type { SurvivorshipRule } from "@/lib/reference-data";

const rules: SurvivorshipRule[] = [
  {
    id: 1,
    entity_type: "counterparty",
    field: "unp",
    strategy: "source_priority",
    source_priority: ["egr", "erp", "1c"],
  },
  {
    id: 2,
    entity_type: "counterparty",
    field: "phone",
    strategy: "manual_only",
    source_priority: [],
  },
  {
    id: 3,
    entity_type: "sku",
    field: "title",
    strategy: "source_priority",
    source_priority: ["1c", "bitrix"],
  },
  {
    id: 4,
    entity_type: "sku",
    field: "weight",
    strategy: "non_empty_wins",
    source_priority: [],
  },
];

describe("SpravMergeRules", () => {
  it("рендерит пустое состояние без бейджа и без таблиц, когда правил нет", () => {
    render(<SpravMergeRules rules={[]} />);
    expect(
      screen.getByText(/Правил пока нет — все поля берут дефолт «непустое замещает»/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/защищены от синка/)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("считает защищённые от синка правила в шапке (2 из 4: source_priority без 1С первым и manual_only)", () => {
    render(<SpravMergeRules rules={rules} />);
    // egr>erp>1c (защищено, первый не 1c) + manual_only (защищено) = 2;
    // 1c>bitrix (первый=1c → НЕ защищено) + non_empty_wins (НЕ защищено)
    expect(screen.getByText("2 защищены от синка")).toBeInTheDocument();
  });

  it("группирует правила по entity_type в отдельные таблицы с человеческими подписями сущностей", () => {
    render(<SpravMergeRules rules={rules} />);
    expect(screen.getByText("Контрагент")).toBeInTheDocument();
    expect(screen.getByText("Номенклатура")).toBeInTheDocument();
    // 4 строки данных + 2 шапки таблиц = 6 строк на 2 таблицы
    const tables = screen.getAllByRole("table");
    expect(tables).toHaveLength(2);
    expect(within(tables[0]).getAllByRole("row")).toHaveLength(3); // header + 2 counterparty rules
    expect(within(tables[1]).getAllByRole("row")).toHaveLength(3); // header + 2 sku rules
  });

  it("показывает метку стратегии и подсказку для source_priority с цепочкой источников по приоритету", () => {
    render(<SpravMergeRules rules={rules} />);
    const unpRow = screen.getByText("unp").closest("tr");
    expect(unpRow).not.toBeNull();
    const withinUnp = within(unpRow as HTMLElement);
    expect(withinUnp.getByText("Приоритет источника")).toBeInTheDocument();
    expect(
      withinUnp.getByText(/Берётся значение из самого доверенного доступного источника/),
    ).toBeInTheDocument();
    // цепочка источников egr › erp › 1С — метки источников по sourceMeta
    expect(withinUnp.getByText("ЕГР")).toBeInTheDocument();
    expect(withinUnp.getByText("ERP")).toBeInTheDocument();
    expect(withinUnp.getByText("1С")).toBeInTheDocument();
  });

  it("помечает правило manual_only как «защищено», а поле с 1С первым источником — «синк обновит»", () => {
    render(<SpravMergeRules rules={rules} />);
    const phoneRow = screen.getByText("phone").closest("tr");
    expect(phoneRow).not.toBeNull();
    expect(within(phoneRow as HTMLElement).getByText("защищено")).toBeInTheDocument();

    const titleRow = screen.getByText("title").closest("tr");
    expect(titleRow).not.toBeNull();
    expect(within(titleRow as HTMLElement).getByText("— синк обновит")).toBeInTheDocument();
  });

  it("рендерит прочерк в цепочке источников, когда source_priority пуст (manual_only/non_empty_wins)", () => {
    render(<SpravMergeRules rules={rules} />);
    const weightRow = screen.getByText("weight").closest("tr");
    expect(weightRow).not.toBeNull();
    expect(within(weightRow as HTMLElement).getByText("—")).toBeInTheDocument();
    expect(within(weightRow as HTMLElement).getByText("Непустое замещает")).toBeInTheDocument();
  });
});
