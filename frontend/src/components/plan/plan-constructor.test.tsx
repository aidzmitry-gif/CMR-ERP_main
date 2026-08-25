import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { nextMonthKey, type PlanSources } from "@/lib/plan-constructor";

// Продавцы грузятся из общего кэша карточек сделок — мок, чтобы не тащить весь deal-card.
vi.mock("@/components/kanban/deal-card", () => ({
  fetchManagersCached: vi.fn(),
}));
// Отправка «РОПу» бьёт по upsertPlan/submitPlan — мок (изолируем компонент от сети api).
vi.mock("@/lib/api", () => ({
  upsertPlan: vi.fn(),
  submitPlan: vi.fn(),
}));

import { PlanConstructor } from "@/components/plan/plan-constructor";
import { fetchManagersCached } from "@/components/kanban/deal-card";
import { submitPlan, upsertPlan } from "@/lib/api";

const managersMock = fetchManagersCached as ReturnType<typeof vi.fn>;
const upsertPlanMock = upsertPlan as ReturnType<typeof vi.fn>;
const submitPlanMock = submitPlan as ReturnType<typeof vi.fn>;

// s1 = committed gross (8000, включён), s2 = regular in_month gross (4000, включён),
// s3 = калькулятор (по умолчанию 0). total = 12000; база 50000 → дефицит 38000.
const SOURCES: PlanSources = {
  month: "2026-08",
  owner: "Иванов И.И.",
  base_gross: 50000,
  committed: [
    { ref: "D-1", title: "Сделка Альфа", when_label: "20.08", revenue: 10000, gross: 8000, probability: 100 },
  ],
  regulars: [
    {
      counterparty: "ООО Ромашка",
      orders_count: 3,
      cycle_days: 30,
      last_order: "2026-06-01",
      expected: "2026-08-15",
      in_month: true,
      avg_check: 5000,
      probability: 80,
      gross: 4000,
    },
    {
      counterparty: "ООО Позже",
      orders_count: 2,
      cycle_days: 60,
      last_order: "2026-05-01",
      expected: "2026-10-01",
      in_month: false,
      avg_check: 3000,
      probability: 50,
      gross: 2500,
    },
  ],
  defaults: { avg_check: 5000, margin_pct: 20, margin_pct_source: "onec" },
  saved_items: [],
};

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

// По умолчанию GET источников отдаёт SOURCES, PUT снапшота — ok. Тесты переопределяют при нужде.
function installFetch(impl?: (url: string, init?: RequestInit) => Promise<Response>) {
  const fn = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url);
    if (impl) return impl(u, init);
    if (u.includes("/api/sales/plan-sources")) return jsonResponse(SOURCES);
    if (u.includes("/api/sales/plan-items")) return jsonResponse({ ok: true });
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

async function renderReady() {
  render(<PlanConstructor ownerId={7} />);
  // База появляется только в ready-ветке — ждём завершения загрузки источников.
  expect(await screen.findByText("База — согласовано с РОПом")).toBeInTheDocument();
}

beforeEach(() => {
  vi.clearAllMocks();
  managersMock.mockResolvedValue([{ name: "Иванов И.И.", regions: [], products: [], load: 0 }]);
  upsertPlanMock.mockResolvedValue({ id: 101 });
  submitPlanMock.mockResolvedValue(true);
  installFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PlanConstructor", () => {
  it("показывает состояние загрузки до прихода источников", async () => {
    render(<PlanConstructor ownerId={7} />);
    // fetchManagersCached ещё не разрешился (микротаск) → синхронно видим загрузку
    expect(screen.getByText("Загрузка источников…")).toBeInTheDocument();
    // даём эффектам отработать, чтобы не осталось «висящих» апдейтов состояния
    await screen.findByText("База — согласовано с РОПом");
  });

  it("рендерит источники: базу, сделку месяца, постоянного клиента и собранный итог", async () => {
    await renderReady();

    // база РОПа
    const baseBlock = screen.getByText("База — согласовано с РОПом").parentElement as HTMLElement;
    expect(baseBlock).toHaveTextContent("50 000 BYN");

    // строки источников
    expect(screen.getByText("Сделка Альфа")).toBeInTheDocument();
    expect(screen.getByText("ООО Ромашка")).toBeInTheDocument();

    // собрано из источников = 8000 + 4000 = 12000
    const collected = screen.getByText("Собрано из источников").parentElement as HTMLElement;
    expect(collected).toHaveTextContent("12 000 BYN");
  });

  it("при дефиците показывает бейдж «Дефицит» на разницу базы и собранного", async () => {
    await renderReady();
    // 50000 − 12000 = 38000
    expect(screen.getByText(/Дефицит\s*38 000 BYN/)).toBeInTheDocument();
  });

  it("снятие галочки со сделки месяца пересчитывает собранный итог", async () => {
    await renderReady();
    const collected = screen.getByText("Собрано из источников").parentElement as HTMLElement;
    expect(collected).toHaveTextContent("12 000 BYN");

    // выключаем committed-строку (gross 8000) → остаётся только постоянный клиент 4000
    fireEvent.click(screen.getByLabelText("Учитывать Сделка Альфа"));
    await waitFor(() => expect(collected).toHaveTextContent("4 000 BYN"));
  });

  it("калькулятор новых по действиям считает сделки/выручку/прибыль из введённой активности", async () => {
    await renderReady();

    // 100 заявок × 10% = 10 сделок; ср.чек 5000 (дефолт) → выручка 50000; маржа 20% → прибыль 10000
    fireEvent.change(screen.getByLabelText("Заявки от маркетинга, шт/мес"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("Конверсия заявка → сделка, %"), { target: { value: "10" } });

    await waitFor(() => {
      const deals = screen.getByText("Сделок (новые)").parentElement as HTMLElement;
      expect(deals).toHaveTextContent("10.0");
    });
    const grossTile = screen.getByText("Вал. прибыль").parentElement as HTMLElement;
    expect(grossTile).toHaveTextContent("10 000 BYN");
  });

  it("ошибка загрузки источников показывает сообщение и кнопку «Повторить»; повтор восстанавливает данные", async () => {
    let calls = 0;
    installFetch(async (u) => {
      if (u.includes("/api/sales/plan-sources")) {
        calls += 1;
        if (calls === 1) return jsonResponse(null, false, 500); // первый заход падает
        return jsonResponse(SOURCES); // повтор успешен
      }
      return jsonResponse({ ok: true });
    });

    render(<PlanConstructor ownerId={7} />);
    expect(await screen.findByText(/Источники недоступны/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("База — согласовано с РОПом")).toBeInTheDocument();
  });

  it("«Отправить РОПу» сохраняет снапшот и все 5 метрик → сообщение об успехе", async () => {
    await renderReady();

    fireEvent.click(screen.getByRole("button", { name: /Отправить РОПу/ }));

    await waitFor(() => expect(screen.getByText(/Отправлено РОПу \(5 метрик\)/)).toBeInTheDocument());
    // gross_profit улетает с целевым значением плана (= собранный итог 12000)
    expect(upsertPlanMock).toHaveBeenCalledWith(
      expect.objectContaining({
        owner_id: 7,
        metric: "gross_profit",
        period_key: nextMonthKey(new Date()),
        target: 12000,
      }),
    );
    expect(submitPlanMock).toHaveBeenCalledTimes(5);
  });

  it("частичный сбой отправки метрик показывает честное «Отправлено частично»", async () => {
    // первая метрика не сохранилась (upsertPlan вернул null) → 4 из 5
    upsertPlanMock.mockResolvedValueOnce(null);
    await renderReady();

    fireEvent.click(screen.getByRole("button", { name: /Отправить РОПу/ }));

    expect(await screen.findByText(/Отправлено частично \(4\/5\)/)).toBeInTheDocument();
  });

  it("провал сохранения снапшота (PUT plan-items) показывает ошибку и не шлёт метрики", async () => {
    installFetch(async (u) => {
      if (u.includes("/api/sales/plan-sources")) return jsonResponse(SOURCES);
      if (u.includes("/api/sales/plan-items")) return jsonResponse(null, false, 500);
      return jsonResponse({});
    });
    await renderReady();

    fireEvent.click(screen.getByRole("button", { name: /Отправить РОПу/ }));

    expect(await screen.findByText(/Не удалось сохранить план/)).toBeInTheDocument();
    expect(upsertPlanMock).not.toHaveBeenCalled();
  });

  it("правка суммы прибыли сделки месяца пересчитывает собранный итог", async () => {
    await renderReady();
    const collected = screen.getByText("Собрано из источников").parentElement as HTMLElement;

    fireEvent.change(screen.getByLabelText("План прибыли Сделка Альфа"), { target: { value: "3000" } });
    // committed 3000 (было 8000) + постоянный в месяце 4000 = 7000
    await waitFor(() => expect(collected).toHaveTextContent("7 000 BYN"));
  });

  it("включение постоянного клиента «вне месяца» добавляет его в собранный итог", async () => {
    await renderReady();
    const collected = screen.getByText("Собрано из источников").parentElement as HTMLElement;
    expect(collected).toHaveTextContent("12 000 BYN");

    // ООО Позже — вне месяца, изначально выключен (in_month: false)
    expect(screen.getByText("подтянуть раньше")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Учитывать ООО Позже"));
    // 12000 + 2500 (gross ООО Позже) = 14500
    await waitFor(() => expect(collected).toHaveTextContent("14 500 BYN"));
  });

  it("сохранённый черновик показывает баннер и применяет его enabled/gross; «пересобрать» возвращает исходные значения", async () => {
    installFetch(async (u) => {
      if (u.includes("/api/sales/plan-sources")) {
        return jsonResponse({
          ...SOURCES,
          saved_items: [
            {
              source: "committed",
              ref: "D-1",
              title: "Сделка Альфа",
              when_label: "20.08",
              revenue: 10000,
              gross: 1000,
              probability: 100,
              enabled: false,
              id: 1,
              owner_id: 7,
              period_key: "2026-08",
              created_at: "2026-07-01",
            },
          ],
        });
      }
      return jsonResponse({ ok: true });
    });
    await renderReady();

    // баннер с датой снапшота (01.07)
    expect(screen.getByText(/Сохранён черновик/)).toBeInTheDocument();
    expect(screen.getByText(/от 01\.07/)).toBeInTheDocument();
    // снапшот применён: строка выключена, сумма 1000 → собрано только 4000 (постоянный)
    const collected = screen.getByText("Собрано из источников").parentElement as HTMLElement;
    expect(collected).toHaveTextContent("4 000 BYN");
    expect(screen.getByLabelText("Учитывать Сделка Альфа")).not.toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /пересобрать из источников/ }));
    // после пересборки — снова исходные committed (включена, 8000) → итог 12000
    await waitFor(() => expect(collected).toHaveTextContent("12 000 BYN"));
    expect(screen.getByLabelText("Учитывать Сделка Альфа")).toBeChecked();
    expect(screen.queryByText(/Сохранён черновик/)).not.toBeInTheDocument();
  });

  it("обратный счёт по умолчанию считает нужное число новых сделок для закрытия дефицита", async () => {
    await renderReady();
    // deficit 38000, ср.чек 5000 × маржа 20% = 1000 прибыли/сделку → 38 сделок; конверсии нулевые → без заявок/звонков
    expect(screen.getByText(/~38 новых сделок/)).toBeInTheDocument();
    // покрытие воронки: leads=0 → коэффициент 0 → «мало, не хватит»
    expect(screen.getByText("заявок на входе мало — на эту цель не хватит")).toBeInTheDocument();
  });

  it("взвешенный прогноз и полоса уверенности считают приход с дисконтом 90% и постоянных по вероятности", async () => {
    await renderReady();
    // взвешенный = committed 8000×0.9=7200 + regular 4000×80%=3200 = 10400
    const weightedBlock = screen.getByText("Взвешенный прогноз").parentElement as HTMLElement;
    expect(weightedBlock).toHaveTextContent("10 400 BYN");

    const bandRow = screen.getByText(/Почти наверняка/);
    expect(bandRow).toHaveTextContent("8 000 BYN"); // guaranteed = s1
    expect(bandRow).toHaveTextContent("10 400 BYN"); // probable = max(s1, weighted)
    expect(bandRow).toHaveTextContent("12 000 BYN"); // ceiling = max(probable, total)
  });

  it("показывает концентрацию плана на доминирующем источнике «Сделки месяца»", async () => {
    await renderReady();
    // s1=8000 из total=12000 → 67%, источник и сделка совпадают по доле → побеждает источник
    expect(screen.getByText(/план на одной ноге: источник «Сделки месяца» — 67%/)).toBeInTheDocument();
  });

  it("без заданной базы РОПа и введённой вручную меньше собранного — вердикт «План набран»", async () => {
    installFetch(async (u) => {
      if (u.includes("/api/sales/plan-sources")) return jsonResponse({ ...SOURCES, base_gross: null });
      return jsonResponse({ ok: true });
    });
    render(<PlanConstructor ownerId={7} />);
    await screen.findByText("База — согласовано с РОПом");

    // база не задана → сначала бейдж «База не задана»
    expect(screen.getByText("База не задана")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("база не задана — впишите"), { target: { value: "5000" } });
    // собрано 12000 ≥ база 5000 → «План набран», перекрытие на 7000
    await waitFor(() => expect(screen.getByText("План набран")).toBeInTheDocument());
    expect(screen.getByText(/перекрывают базу на 7 000 BYN/)).toBeInTheDocument();
  });

  it("шапка источника «Сделки месяца» показывает долю плана от базы", async () => {
    await renderReady();
    // 8000 / 50000 = 16% (первый источник — «Сделки месяца»)
    const shareLabel = screen.getAllByText("доля плана")[0];
    expect(shareLabel.parentElement).toHaveTextContent("16%");
  });
});
