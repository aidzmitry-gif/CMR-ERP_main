import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SpravCard } from "@/components/erp/spravochniki/sprav-card";
import type { CounterpartyCard } from "@/lib/reference-data";

const baseCard: CounterpartyCard = {
  id: 42,
  name: "ООО Ромашка",
  unp: "192766048",
  is_active: true,
  merged_into_id: null,
  provenance: {},
  aliases: [],
  merged_duplicates: [],
  contacts: [],
  audit: [],
  touches: [],
  touch_summary: null,
};

function clone(over: Partial<CounterpartyCard> = {}): CounterpartyCard {
  return { ...baseCard, ...over };
}

describe("SpravCard", () => {
  it("рисует шапку: наименование, УНП, статус «Активен» и id", () => {
    render(<SpravCard card={baseCard} />);
    expect(screen.getByRole("heading", { name: "ООО Ромашка" })).toBeInTheDocument();
    // "УНП 192766048" встречается и в шапке (span), и в SourceTag — оба честны
    expect(screen.getAllByText("УНП 192766048").length).toBe(2);
    // «Активен» — в бейдже шапки и в поле «Статус»
    expect(screen.getAllByText("Активен").length).toBe(2);
    expect(screen.getByText("#42")).toBeInTheDocument();
  });

  it("в архиве вместо «Активен» показывает «В архиве» (в шапке и в поле «Статус»)", () => {
    render(<SpravCard card={clone({ is_active: false })} />);
    expect(screen.getAllByText("В архиве").length).toBe(2);
    expect(screen.queryByText("Активен")).not.toBeInTheDocument();
  });

  it("без УНП — плашка УНП в шапке не рисуется, а в поле «УНП» — прочерк", () => {
    render(<SpravCard card={clone({ unp: null })} />);
    // плашки «УНП …» в шапке нет вовсе; SourceTag честно рисует «УНП —»
    expect(screen.queryByText(/^УНП \d/)).not.toBeInTheDocument();
    expect(screen.getByText("УНП —")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("без контактов — честное «Контактов не найдено»", () => {
    render(<SpravCard card={baseCard} />);
    expect(screen.getByText("Контактов не найдено")).toBeInTheDocument();
  });

  it("контакты: основной помечен, телефон и email рендерятся", () => {
    render(
      <SpravCard
        card={clone({
          contacts: [
            { id: 1, full_name: "Иван Петров", phone: "+375291234567", email: "ivan@example.com", is_primary: true },
            { id: 2, full_name: "Анна Смирнова", phone: null, email: null, is_primary: false },
          ],
        })}
      />,
    );
    expect(screen.getByText("Иван Петров")).toBeInTheDocument();
    expect(screen.getByText("основной")).toBeInTheDocument();
    expect(screen.getByText("+375291234567")).toBeInTheDocument();
    expect(screen.getByText("ivan@example.com")).toBeInTheDocument();
    expect(screen.getByText("Анна Смирнова")).toBeInTheDocument();
    // у второго контакта нет бейджа «основной» — ровно один на странице
    expect(screen.getAllByText("основной").length).toBe(1);
  });

  it("без provenance блок «Доверие к данным» не рендерится", () => {
    render(<SpravCard card={baseCard} />);
    expect(screen.queryByText("Доверие к данным")).not.toBeInTheDocument();
  });

  it("с provenance — сводка по источникам со склонением («2 поля», «1 поле»)", () => {
    render(
      <SpravCard
        card={clone({
          provenance: {
            name: { source: "egr", at: "2026-01-01" },
            unp: { source: "egr", at: "2026-01-01" },
            is_active: { source: "manual", at: "2026-02-01" },
          },
        })}
      />,
    );
    const panel = screen.getByText("Доверие к данным").closest("div") as HTMLElement;
    expect(within(panel).getByText("ЕГР")).toBeInTheDocument();
    expect(within(panel).getByText("2 поля")).toBeInTheDocument();
    expect(within(panel).getByText("Вручную")).toBeInTheDocument();
    expect(within(panel).getByText("1 поле")).toBeInTheDocument();
  });

  it("golden record: без алиасов — «Эталон без алиасов», источник мдм", () => {
    render(<SpravCard card={baseCard} />);
    expect(screen.getByText("Эталон без алиасов")).toBeInTheDocument();
  });

  it("golden record: с алиасами 1С — счётчик источников и склонение, источник «mdm/1c»", () => {
    render(
      <SpravCard
        card={clone({
          aliases: [
            { source: "1c", external_ref: "1c-100", created_at: "2026-01-01" },
            { source: "bitrix", external_ref: "b-7", created_at: "2026-01-02" },
          ],
        })}
      />,
    );
    expect(screen.getByText("Собрана из 2 источника")).toBeInTheDocument();
    expect(screen.getByText("1c · 1c-100")).toBeInTheDocument();
    expect(screen.getByText("bitrix · b-7")).toBeInTheDocument();
  });

  it("golden record: одиночный алиас склоняется как «1 источника»", () => {
    render(
      <SpravCard
        card={clone({ aliases: [{ source: "manual", external_ref: "m-1", created_at: "2026-01-01" }] })}
      />,
    );
    expect(screen.getByText("Собрана из 1 источника")).toBeInTheDocument();
  });

  it("без слитых дублей блок «Слитые дубли» не рендерится", () => {
    render(<SpravCard card={baseCard} />);
    expect(screen.queryByText("Слитые дубли")).not.toBeInTheDocument();
  });

  it("слитые дубли: рендерит имя и id, «Слияние обратимо»", () => {
    render(
      <SpravCard
        card={clone({ merged_duplicates: [{ id: 7, name: "ООО Дубль" }] })}
      />,
    );
    expect(screen.getByText("Слитые дубли")).toBeInTheDocument();
    expect(screen.getByText("ООО Дубль")).toBeInTheDocument();
    expect(screen.getByText("#7")).toBeInTheDocument();
    expect(screen.getByText("Слияние обратимо.")).toBeInTheDocument();
  });

  it("без касаний блок «Досье 360°» не рендерится", () => {
    render(<SpravCard card={baseCard} />);
    expect(screen.queryByText("Досье 360° — история касаний")).not.toBeInTheDocument();
  });

  it("с касаниями — сводка звонков/сделок/сообщений и последний контакт", () => {
    render(
      <SpravCard
        card={clone({
          touches: [
            { kind: "call", ts: "2026-01-15 10:30:00", channel: "телефон", direction: "in", title: "Звонок клиенту", ref: "call:1" },
            { kind: "deal", ts: "2026-01-16 12:00:00", channel: null, direction: null, title: "Сделка №5", ref: "deal:5" },
          ],
          touch_summary: { calls: 1, deals: 1, messages: 0, last_contact: "2026-01-16 12:00:00" },
        })}
      />,
    );
    expect(screen.getByText("Досье 360° — история касаний")).toBeInTheDocument();
    expect(screen.getByText("📞 1 звонок")).toBeInTheDocument();
    expect(screen.getByText("🤝 1 сделка")).toBeInTheDocument();
    expect(screen.getByText("💬 0 сообщений")).toBeInTheDocument();
    expect(screen.getByText("последний контакт 16.01.2026 12:00")).toBeInTheDocument();
    expect(screen.getByText("Звонок клиенту")).toBeInTheDocument();
    expect(screen.getByText("входящий")).toBeInTheDocument();
    expect(screen.getByText("Сделка №5")).toBeInTheDocument();
  });

  it("без записей аудита — честное «Истории изменений пока нет»", () => {
    render(<SpravCard card={baseCard} />);
    expect(screen.getByText("Истории изменений пока нет")).toBeInTheDocument();
  });

  it("аудит: строка таблицы с действием, актором и датой DD.MM.YYYY", () => {
    render(
      <SpravCard
        card={clone({
          audit: [{ id: 1, ts: "2026-06-15 23:30:00.123456", actor: "ivan@example.com", action: "update", detail: {} }],
        })}
      />,
    );
    expect(screen.getByText("update")).toBeInTheDocument();
    expect(screen.getByText("ivan@example.com")).toBeInTheDocument();
    expect(screen.getByText("15.06.2026")).toBeInTheDocument();
  });
});
