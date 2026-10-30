import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Stage } from "@/lib/types";

const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api", () => ({ updateStage: vi.fn() }));
import { updateStage } from "@/lib/api";
import { StageHeading } from "./stage-heading";

const stage: Stage = { id: "qual", title: "Квалификация", description: "Комментарий для команды.\nВторая строка.", color: "#2563eb", count: 0, sum: 0, deals: [] };
const originalShow = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
beforeAll(() => {
  // jsdom does not implement the browser top layer/focus trap; the real browser lab checks those.
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
});
afterAll(() => {
  for (const [name, descriptor] of [["showModal", originalShow], ["close", originalClose]] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
  }
});
function load(description = stage.description) {
  return { ok: true, json: async () => [{ code: "qual", title: stage.title, color: stage.color, description }] };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(updateStage).mockReset().mockResolvedValue(true);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(load()));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("StageHeading", () => {
  it("shows multiline plain-text instructions on focus and dismisses with Escape", () => {
    render(<StageHeading stage={stage} onSaved={vi.fn()} />);
    fireEvent.focus(screen.getByRole("button", { name: "Описание стадии «Квалификация»" }));
    expect(screen.getByRole("tooltip").textContent).toBe(stage.description);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("supports tap-to-pin and outside dismissal without an automatic write", () => {
    render(<StageHeading stage={stage} onSaved={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "Описание стадии «Квалификация»" });
    fireEvent.click(trigger);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(updateStage).not.toHaveBeenCalled();
  });

  it("has no empty tooltip and never interprets stored markup as HTML", () => {
    const view = render(<StageHeading stage={{ ...stage, description: "" }} onSaved={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Описание стадии/ })).not.toBeInTheDocument();
    view.rerender(<StageHeading stage={{ ...stage, description: "<b>Текст</b>" }} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Описание стадии/ }));
    expect(screen.getByRole("tooltip").textContent).toBe("<b>Текст</b>");
    expect(screen.getByRole("tooltip").querySelector("b")).toBeNull();
  });

  it("loads current metadata, saves title/color/description and refreshes only after confirmation", async () => {
    vi.mocked(updateStage).mockResolvedValue(true);
    const onSaved = vi.fn();
    render(<StageHeading stage={stage} onSaved={onSaved} />);
    fireEvent.click(screen.getByRole("button", { name: /Редактировать стадию/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Сохранить" })).toBeEnabled());
    fireEvent.change(screen.getByRole("textbox", { name: "Название стадии" }), { target: { value: "Новая квалификация" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Описание стадии" }), { target: { value: "Новая инструкция\nПроверка" } });
    fireEvent.change(screen.getByLabelText("Цвет стадии"), { target: { value: "#84cc16" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ title: "Новая квалификация", color: "#84cc16", description: "Новая инструкция\nПроверка" }));
    expect(updateStage).toHaveBeenCalledWith("qual", expect.objectContaining({ description: "Новая инструкция\nПроверка" }));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("keeps the edited draft and old heading when saving is not confirmed", async () => {
    vi.mocked(updateStage).mockResolvedValue(false);
    const onSaved = vi.fn();
    render(<StageHeading stage={stage} onSaved={onSaved} />);
    fireEvent.click(screen.getByRole("button", { name: /Редактировать стадию/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Сохранить" })).toBeEnabled());
    fireEvent.change(screen.getByRole("textbox", { name: "Описание стадии" }), { target: { value: "Не потерять" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Сохранение не подтверждено");
    expect(screen.getByRole("textbox", { name: "Описание стадии" })).toHaveValue("Не потерять");
    expect(onSaved).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("blocks saving if the current stage cannot be read", async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: false } as Response);
    render(<StageHeading stage={stage} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Редактировать стадию/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить стадию");
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Описание стадии" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Отмена" })).toBeEnabled();
    expect(updateStage).not.toHaveBeenCalled();
  });

  it("cancels an edited description without writing", async () => {
    render(<StageHeading stage={stage} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Редактировать стадию/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Сохранить" })).toBeEnabled());
    fireEvent.change(screen.getByRole("textbox", { name: "Описание стадии" }), { target: { value: "Отмена" } });
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Редактировать стадию/ })).toHaveFocus();
    expect(updateStage).not.toHaveBeenCalled();
  });

  it("blocks a second save while the first request is pending", async () => {
    let finish!: (value: boolean) => void;
    vi.mocked(updateStage).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    render(<StageHeading stage={stage} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Редактировать стадию/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Сохранить" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(screen.getByRole("button", { name: "Сохранение…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Отмена" })).toBeDisabled();
    expect(updateStage).toHaveBeenCalledOnce();
    await act(async () => { finish(true); });
  });
});
