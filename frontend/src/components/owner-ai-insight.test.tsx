import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("@/lib/api", () => ({ fetchOwnerInsight: vi.fn() }));
import { fetchOwnerInsight } from "@/lib/api";
import { OwnerAiInsight } from "./owner-ai-insight";
beforeEach(() => vi.mocked(fetchOwnerInsight).mockReset());

it("reports a failed insight as unavailable and supports retry", async () => {
  vi.mocked(fetchOwnerInsight).mockResolvedValueOnce(null).mockResolvedValueOnce("Проверьте просроченную оплату");
  render(<OwnerAiInsight />);
  fireEvent.click(screen.getByRole("button", { name: "Сгенерировать" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("недоступна");
  expect(screen.queryByText(/feature-flag/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Сгенерировать" }));
  expect(await screen.findByText("Проверьте просроченную оплату")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("hides an old insight during a new request and after a network failure", async () => {
  let done!: (value: string | null) => void;
  vi.mocked(fetchOwnerInsight).mockResolvedValueOnce("Старая сводка")
    .mockReturnValueOnce(new Promise(resolve => { done = resolve; }));
  render(<OwnerAiInsight />);
  fireEvent.click(screen.getByRole("button", { name: "Сгенерировать" }));
  await screen.findByText("Старая сводка");
  fireEvent.click(screen.getByRole("button", { name: "Сгенерировать" }));
  expect(screen.queryByText("Старая сводка")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Анализ…" })).toBeDisabled();
  await act(async () => done(null));
  expect(screen.getByRole("alert")).toBeInTheDocument();
});
