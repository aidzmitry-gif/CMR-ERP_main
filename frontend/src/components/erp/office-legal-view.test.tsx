import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OfficeLegalView } from "@/components/erp/office-legal-view";

// Компонент ходит в backend напрямую через глобальный fetch (не через @/lib/api),
// поэтому подменяем window.fetch. `listData` — что отдаёт GET /api/office/contracts;
// `postHandler` — реакция на POST создания договора (по умолчанию успех).
type Contract = {
  id: number;
  number: string;
  counterparty_name: string;
  contract_type: string;
  status: string;
  signed_at: string | null;
  expires_at: string | null;
  amount_byn: string;
  description: string;
};

let listData: Contract[] = [];
let postHandler: () => { ok: boolean; status: number };
// URL-и всех GET-ов на список — чтобы проверять, что фильтры уходят в query.
let getUrls: string[] = [];
let postBodies: string[] = [];

function jsonResponse(body: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

const contract = (over: Partial<Contract> = {}): Contract => ({
  id: 1,
  number: "ДОГ-001",
  counterparty_name: "ООО Поставщик",
  contract_type: "supply",
  status: "active",
  signed_at: "2026-01-10",
  expires_at: "2026-12-31",
  amount_byn: "12500.00",
  description: "Поставка металлопроката",
  ...over,
});

beforeEach(() => {
  listData = [];
  postHandler = () => ({ ok: true, status: 200 });
  getUrls = [];
  postBodies = [];

  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        postBodies.push(String(init.body));
        const r = postHandler();
        return jsonResponse({ id: 999 }, r.ok, r.status);
      }
      getUrls.push(String(url));
      return jsonResponse(listData);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("OfficeLegalView", () => {
  it("на старте грузит список и показывает пустое состояние «Договоров нет»", async () => {
    render(<OfficeLegalView />);
    await waitFor(() => expect(getUrls.length).toBeGreaterThan(0));
    expect(getUrls[0]).toContain("/api/office/contracts");
    expect(await screen.findByText("Договоров нет")).toBeInTheDocument();
  });

  it("рендерит строку договора: номер, контрагент, русские подписи типа/статуса и сумму", async () => {
    listData = [contract()];
    render(<OfficeLegalView />);

    expect(await screen.findByText("ДОГ-001")).toBeInTheDocument();
    const row = screen.getByText("ДОГ-001").closest("tr") as HTMLElement;
    expect(within(row).getByText("ООО Поставщик")).toBeInTheDocument();
    // человекочитаемые подписи, а не сырые ключи supply/active
    expect(within(row).getByText("Поставка")).toBeInTheDocument();
    expect(within(row).getByText("Активный")).toBeInTheDocument();
    expect(within(row).getByText("12500.00")).toBeInTheDocument();
    expect(within(row).getByText("2026-01-10")).toBeInTheDocument();
    // «Договоров нет» не показывается, когда есть данные
    expect(screen.queryByText("Договоров нет")).not.toBeInTheDocument();
  });

  it("прочерк вместо пустых дат подписания/истечения", async () => {
    listData = [contract({ signed_at: null, expires_at: null })];
    render(<OfficeLegalView />);

    const row = (await screen.findByText("ДОГ-001")).closest("tr") as HTMLElement;
    expect(within(row).getAllByText("—")).toHaveLength(2);
  });

  it("смена фильтра статуса перезапрашивает список с параметром status в query", async () => {
    render(<OfficeLegalView />);
    await waitFor(() => expect(getUrls.length).toBe(1));
    // первый запрос — без фильтров
    expect(getUrls[0]).not.toContain("status=");

    const statusSelect = screen.getAllByRole("combobox")[0];
    fireEvent.change(statusSelect, { target: { value: "terminated" } });

    await waitFor(() => expect(getUrls.length).toBe(2));
    expect(getUrls[1]).toContain("status=terminated");
  });

  it("кнопка «+ Договор» разворачивает форму и переключается в «Отмена»", async () => {
    render(<OfficeLegalView />);
    await screen.findByText("Договоров нет");

    const toggle = screen.getByRole("button", { name: "+ Договор" });
    expect(screen.queryByText("Новый договор")).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.getByText("Новый договор")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отмена" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByText("Новый договор")).not.toBeInTheDocument();
  });

  it("создание договора шлёт POST с введённым контрагентом, закрывает форму и перезагружает список", async () => {
    render(<OfficeLegalView />);
    await screen.findByText("Договоров нет");
    fireEvent.click(screen.getByRole("button", { name: "+ Договор" }));

    fireEvent.change(screen.getByPlaceholderText("ООО Поставщик"), {
      target: { value: "ООО Новый Клиент" },
    });
    // после успешного создания список должен показать созданный договор
    listData = [contract({ counterparty_name: "ООО Новый Клиент", number: "ДОГ-777" })];

    fireEvent.click(screen.getByRole("button", { name: "Создать" }));

    await waitFor(() => expect(postBodies.length).toBe(1));
    const sent = JSON.parse(postBodies[0]);
    expect(sent.counterparty_name).toBe("ООО Новый Клиент");
    expect(sent.contract_type).toBe("supply");

    // форма закрылась и произошёл повторный GET (mount + reload = 2)
    await waitFor(() => expect(screen.queryByText("Новый договор")).not.toBeInTheDocument());
    expect(getUrls.length).toBe(2);
    expect(await screen.findByText("ДОГ-777")).toBeInTheDocument();
  });

  it("сбой POST показывает «Ошибка <код>» и оставляет форму открытой", async () => {
    render(<OfficeLegalView />);
    await screen.findByText("Договоров нет");
    fireEvent.click(screen.getByRole("button", { name: "+ Договор" }));
    fireEvent.change(screen.getByPlaceholderText("ООО Поставщик"), {
      target: { value: "ООО Провал" },
    });

    postHandler = () => ({ ok: false, status: 422 });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));

    expect(await screen.findByText("Ошибка 422")).toBeInTheDocument();
    // форма не закрылась — ошибку видно на месте
    expect(screen.getByText("Новый договор")).toBeInTheDocument();
  });
});
