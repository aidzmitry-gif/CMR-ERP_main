import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NextStepComposer } from "@/components/kanban/next-step-composer";
import type { Deal } from "@/lib/types";

const deal: Deal = {
  id: "1",
  number: "CRM-1",
  company: "ООО",
  description: "d",
  amount: 100,
  priority: "Средний",
  owner: "И",
};

// Локальное время (не UTC) — симметрично presetDateISO/board.test.ts.
const NOW = new Date(2026, 5, 11, 12, 0, 0).getTime(); // 11.06.2026

describe("NextStepComposer (слайс 4, «след. шаг в 2 клика»)", () => {
  it("закрыт: видна только строка-триггер «+ след. шаг» (шага нет), без панели пресетов", () => {
    render(
      <NextStepComposer deal={deal} stageId="new" open={false} onOpenChange={vi.fn()} onSave={vi.fn()} now={NOW} />,
    );
    expect(screen.getByText("+ след. шаг")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Сохранить" })).toBeNull();
  });

  it("триггер показывает текущий шаг, если он уже есть", () => {
    render(
      <NextStepComposer
        deal={{ ...deal, nextStep: "Позвонить" }}
        stageId="new"
        open={false}
        onOpenChange={vi.fn()}
        onSave={vi.fn()}
        now={NOW}
      />,
    );
    expect(screen.getByText("Позвонить")).toBeInTheDocument();
    expect(screen.queryByText("+ след. шаг")).toBeNull();
  });

  it("клик по триггеру зовёт onOpenChange(true)", () => {
    const onOpenChange = vi.fn();
    render(
      <NextStepComposer deal={deal} stageId="new" open={false} onOpenChange={onOpenChange} onSave={vi.fn()} now={NOW} />,
    );
    fireEvent.click(screen.getByText("+ след. шаг"));
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it("открыт: рендерит пресеты стадии (qual) и кнопку «Сохранить»", () => {
    render(
      <NextStepComposer deal={deal} stageId="qual" open onOpenChange={vi.fn()} onSave={vi.fn()} now={NOW} />,
    );
    expect(screen.getByText("Отправить КП")).toBeInTheDocument();
    expect(screen.getByText("Уточнить бюджет и сроки")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeInTheDocument();
  });

  it("неизвестная стадия — дефолтные пресеты (DEFAULT_NEXT_STEP_TEMPLATES)", () => {
    render(
      <NextStepComposer deal={deal} stageId="какая-то" open onOpenChange={vi.fn()} onSave={vi.fn()} now={NOW} />,
    );
    expect(screen.getByText("Позвонить клиенту")).toBeInTheDocument();
  });

  it("won/lost — без пресетов стадии рендерит дефолтные (nextStepTemplatesFor не даёт []) ", () => {
    render(
      <NextStepComposer deal={deal} stageId="won" open onOpenChange={vi.fn()} onSave={vi.fn()} now={NOW} />,
    );
    expect(screen.getByText("Позвонить клиенту")).toBeInTheDocument();
  });

  it("клик по пресету текста + «Сохранить» (2 клика) → onSave с текстом и ISO-датой пресета", () => {
    const onSave = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <NextStepComposer deal={deal} stageId="qual" open onOpenChange={onOpenChange} onSave={onSave} now={NOW} />,
    );
    fireEvent.click(screen.getByText("Отправить КП")); // 1-й пресет qual, offsetDays=1
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onSave).toHaveBeenCalledWith({ text: "Отправить КП", atISO: "2026-06-12T09:00:00" });
    expect(onOpenChange).toHaveBeenCalledWith(false); // сохранение закрывает композер
  });

  it("пресет срока «Сегодня» переопределяет дату у уже выбранного текстового пресета", () => {
    const onSave = vi.fn();
    render(
      <NextStepComposer deal={deal} stageId="qual" open onOpenChange={vi.fn()} onSave={onSave} now={NOW} />,
    );
    fireEvent.click(screen.getByText("Отправить КП"));
    fireEvent.click(screen.getByRole("button", { name: "Сегодня" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onSave).toHaveBeenCalledWith({ text: "Отправить КП", atISO: "2026-06-11T09:00:00" });
  });

  it("без выбора пресета «Сохранить» уже активна — использует дефолт (первый пресет стадии)", () => {
    const onSave = vi.fn();
    render(
      <NextStepComposer deal={deal} stageId="qual" open onOpenChange={vi.fn()} onSave={onSave} now={NOW} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onSave).toHaveBeenCalledWith({ text: "Отправить КП", atISO: "2026-06-12T09:00:00" });
  });

  it("свой текст (input) переопределяет пресет — «Сохранить» шлёт введённый текст", () => {
    const onSave = vi.fn();
    render(
      <NextStepComposer deal={deal} stageId="qual" open onOpenChange={vi.fn()} onSave={onSave} now={NOW} />,
    );
    fireEvent.change(screen.getByPlaceholderText("Свой текст шага…"), {
      target: { value: "Согласовать спецификацию с клиентом" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ text: "Согласовать спецификацию с клиентом" }),
    );
  });

  it("если шаг уже есть — показывает «Текущий шаг» и кнопки «✓ Выполнен»/«Выполнен, без следующего»", () => {
    render(
      <NextStepComposer
        deal={{ ...deal, nextStep: "Позвонить", nextStepAt: "2026-06-10T09:00:00" }}
        stageId="qual"
        open
        onOpenChange={vi.fn()}
        onSave={vi.fn()}
        now={NOW}
      />,
    );
    expect(screen.getByText("Текущий шаг")).toBeInTheDocument();
    // "Позвонить" встречается дважды: в триггере (строка шага) и в сводке «Текущий шаг» панели.
    expect(screen.getAllByText("Позвонить").length).toBe(2);
    expect(screen.getByRole("button", { name: "✓ Выполнен" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Выполнен, без следующего" })).toBeInTheDocument();
  });

  it("если шага ещё нет — блока «Текущий шаг»/«Выполнен» нет", () => {
    render(
      <NextStepComposer deal={deal} stageId="qual" open onOpenChange={vi.fn()} onSave={vi.fn()} now={NOW} />,
    );
    expect(screen.queryByText("Текущий шаг")).toBeNull();
    expect(screen.queryByRole("button", { name: "✓ Выполнен" })).toBeNull();
  });

  it("«Выполнен, без следующего» → onSave(null/null) и закрывает композер", () => {
    const onSave = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <NextStepComposer
        deal={{ ...deal, nextStep: "Позвонить" }}
        stageId="qual"
        open
        onOpenChange={onOpenChange}
        onSave={onSave}
        now={NOW}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Выполнен, без следующего" }));
    expect(onSave).toHaveBeenCalledWith({ text: null, atISO: null });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("«✓ Выполнен» → onSave(null/null), но НЕ закрывает композер (жест «дальше — следующий шаг»)", () => {
    const onSave = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <NextStepComposer
        deal={{ ...deal, nextStep: "Позвонить" }}
        stageId="qual"
        open
        onOpenChange={onOpenChange}
        onSave={onSave}
        now={NOW}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "✓ Выполнен" }));
    expect(onSave).toHaveBeenCalledWith({ text: null, atISO: null });
    expect(onOpenChange).not.toHaveBeenCalled();
    // Композер остаётся открытым с пресетами дефолтной стадии, готовый к следующему шагу.
    expect(screen.getByText("Отправить КП")).toBeInTheDocument();
  });

  it("клик по бэкдропу закрывает композер без onSave", () => {
    const onSave = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <NextStepComposer deal={deal} stageId="qual" open onOpenChange={onOpenChange} onSave={onSave} now={NOW} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Закрыть композер следующего шага" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSave).not.toHaveBeenCalled();
  });
});
