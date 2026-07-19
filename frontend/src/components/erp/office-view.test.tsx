import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OfficeView } from "@/components/erp/office-view";
import type { Delivery } from "@/lib/office-delivery";

// Доска «Документы» приходит готовым React-узлом от SSR-родителя — подменяем маркером,
// чтобы отличать его wrapper (contents/hidden) от секции «Доставка».
const board = <div>Воронка-заглушка</div>;

// Тяжёлая отгрузка (≥300 кг) без перевозчика → нужна заявка; лёгкая — нет.
const heavy: Delivery = { id: 1, code: "A1", company: "ООО Тяж", weight: "400 кг", amount: 300, stage: "new" };
const light: Delivery = { id: 2, code: "A2", company: "ООО Лёгк", weight: "50 кг", amount: 200, stage: "new" };

// По умолчанию оба useEffect-фетча (docs/carriers) отдают «не ok» → компонент остаётся
// на initialDeliveries/OFFICE_CARRIERS, UI не падает. Отдельные тесты переопределяют fetch.
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 404, json: async () => [] })),
  );
});
afterEach(() => vi.unstubAllGlobals());

// wrapper-див вокруг узла: класс "contents" (активная вкладка) или "hidden" (скрытая)
function boardWrapper() {
  return screen.getByText("Воронка-заглушка").parentElement as HTMLElement;
}
function deliveryWrapper() {
  return screen.getByRole("heading", { name: "Доставка и трекинг" }).closest("main")
    ?.parentElement as HTMLElement;
}

describe("OfficeView", () => {
  it("рендерит обе вкладки, по умолчанию активна «Документы» и показывает доску", () => {
    render(<OfficeView board={board} initialDeliveries={[heavy, light]} />);

    expect(screen.getByRole("button", { name: /Документы/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Доставка/ })).toBeInTheDocument();
    // docs активна → доска в contents, секция доставки скрыта
    expect(boardWrapper().className).toContain("contents");
    expect(deliveryWrapper().className).toContain("hidden");
  });

  it("бейдж на «Доставка» = число тяжёлых отгрузок без перевозчика", () => {
    render(
      <OfficeView
        board={board}
        initialDeliveries={[
          heavy, // 400 кг, без перевозчика → нужна заявка
          { ...heavy, id: 3, weight: "500 кг" }, // ещё одна тяжёлая без перевозчика
          { ...heavy, id: 4, weight: "700 кг", carrier: "СДЭК" }, // тяжёлая, но перевозчик есть — не считается
          light, // лёгкая — не считается
        ]}
      />,
    );
    // бейдж живёт внутри кнопки «Доставка»
    expect(screen.getByRole("button", { name: /Доставка/ }).textContent).toContain("2");
  });

  it("бейдж не показан, когда все тяжёлые отгрузки уже с перевозчиком", () => {
    render(
      <OfficeView
        board={board}
        initialDeliveries={[{ ...heavy, carrier: "Деловые Линии" }, light]}
      />,
    );
    // текст кнопки — только «Доставка», без цифры-бейджа
    expect(screen.getByRole("button", { name: /Доставка/ }).textContent?.trim()).toBe("Доставка");
  });

  it("клик по «Доставка» делает секцию активной (contents), а доску — скрытой", () => {
    render(<OfficeView board={board} initialDeliveries={[heavy, light]} />);

    fireEvent.click(screen.getByRole("button", { name: /Доставка/ }));

    expect(deliveryWrapper().className).toContain("contents");
    expect(boardWrapper().className).toContain("hidden");
  });

  it("считает и показывает сумму отгрузок в BYN", () => {
    render(<OfficeView board={board} initialDeliveries={[heavy, light]} />);
    // 300 + 200 = 500 BYN (formatByn) — реальный подсчёт, не мок
    expect(screen.getByText("500 BYN")).toBeInTheDocument();
  });

  it("оформление заявки перевозчику проставляет перевозчика в строке и гасит бейдж", async () => {
    render(<OfficeView board={board} initialDeliveries={[heavy, light]} />);

    // до заявки: бейдж = 1, перевозчика в строке нет
    expect(screen.getByRole("button", { name: /Доставка/ }).textContent).toContain("1");

    fireEvent.click(screen.getByRole("button", { name: /Заявка перевозчику/ }));
    // открылась модалка заявки
    const submit = await screen.findByRole("button", { name: /Отправить заявку/ });
    fireEvent.click(submit);

    // eligible[0] для тяжёлого груза = «Деловые Линии» (первый heavy в OFFICE_CARRIERS)
    expect(await screen.findByText("Деловые Линии")).toBeInTheDocument();
    // needCarrierRequest упал до 0 → бейдж исчез
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Доставка/ }).textContent?.trim()).toBe("Доставка"),
    );
    // модалка закрылась
    expect(screen.queryByRole("button", { name: /Отправить заявку/ })).not.toBeInTheDocument();
  });

  it("выбор другого перевозчика в модалке проставляет именно его", async () => {
    render(<OfficeView board={board} initialDeliveries={[heavy]} />);

    fireEvent.click(screen.getByRole("button", { name: /Заявка перевозчику/ }));
    await screen.findByRole("button", { name: /Отправить заявку/ });
    // меняем перевозчика на DPD (тоже heavy)
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "dpd" } });
    fireEvent.click(screen.getByRole("button", { name: /Отправить заявку/ }));

    expect(await screen.findByText("DPD")).toBeInTheDocument();
    // «Деловые Линии» (дефолт) НЕ был назначен
    expect(screen.queryByText("Деловые Линии")).not.toBeInTheDocument();
  });

  it("живые документы из /api/office/docs заменяют демо-отгрузки", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/office/docs") {
          return {
            ok: true,
            json: async () => [
              {
                id: 77,
                number: "LIVE-77",
                company: "ООО Живой Док",
                amount: 500,
                delivery: "",
                docs_status: "В пути",
                stage: "shipped",
                region: "Гродно",
                weight: "120 кг",
              },
            ],
          };
        }
        return { ok: false, status: 404, json: async () => [] };
      }),
    );
    render(<OfficeView board={board} initialDeliveries={[heavy, light]} />);

    // после подгрузки живого дока в таблице появляется его компания и стадия «В пути»
    expect(await screen.findByText("ООО Живой Док")).toBeInTheDocument();
    // «В пути» есть и как KPI-подпись, и как бейдж стадии строки → минимум 2 совпадения
    expect(screen.getAllByText("В пути").length).toBeGreaterThanOrEqual(2);
    // демо-отгрузка вытеснена
    expect(screen.queryByText("ООО Тяж")).not.toBeInTheDocument();
  });

  it("заявка по живому документу (officeStage=ready) шлёт POST carrier-request на backend", async () => {
    const fetchMock = vi.fn(async (url: string, opts?: RequestInit) => {
      if (url === "/api/office/docs") {
        return {
          ok: true,
          json: async () => [
            {
              id: 88,
              number: "LIVE-88",
              company: "ООО Готово",
              amount: 900,
              delivery: "",
              docs_status: "",
              stage: "ready", // canRequestCarrier → кнопка заявки доступна
              region: "Минск",
              weight: "600 кг", // тяжёлая → нужна заявка
            },
          ],
        };
      }
      void opts;
      return { ok: true, status: 200, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<OfficeView board={board} initialDeliveries={[heavy]} />);

    // дождаться подмены на живой документ
    await screen.findByText("ООО Готово");
    fireEvent.click(screen.getByRole("button", { name: /Заявка перевозчику/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Отправить заявку/ }));

    // ушёл POST на оформление заявки перевозчику для документа 88
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => u === "/api/office/docs/88/carrier-request");
      expect(call).toBeTruthy();
      expect((call?.[1] as RequestInit)?.method).toBe("POST");
    });
    // тело содержит выбранного перевозчика и регион документа
    const post = fetchMock.mock.calls.find(([u]) => u === "/api/office/docs/88/carrier-request");
    const body = JSON.parse((post?.[1] as RequestInit)?.body as string);
    expect(body).toMatchObject({ carrier: "dellin", region: "Минск" });
  });
});
