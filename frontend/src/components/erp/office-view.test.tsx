import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { OfficeView } from "@/components/erp/office-view";

vi.mock("@/components/erp/office-review-queue", () => ({ OfficeReviewQueue: () => <div>Назначения проверяющих</div> }));
afterEach(() => { vi.unstubAllGlobals(); });
const board = <div>Нативная воронка документов</div>;
it("preserves the mounted native funnel and loads delivery only on explicit tab selection", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json([])); vi.stubGlobal("fetch", fetcher);
  render(<OfficeView board={board} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Доставка" }));
  expect(await screen.findByText("Нет доступных документов")).toBeInTheDocument();
  expect(screen.getByText("Нативная воронка документов").parentElement?.className).toBe("hidden");
  fireEvent.click(screen.getByRole("button", { name: "Документы" }));
  expect(screen.getByText("Нативная воронка документов").parentElement?.className).toBe("contents");
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("shows an empty successful response without demonstration deliveries or invented KPI totals", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json([])));
  render(<OfficeView board={board} />); fireEvent.click(screen.getByRole("button", { name: "Доставка" }));
  expect(await screen.findByText("Нет доступных документов")).toBeInTheDocument();
  expect(screen.queryByText(/BYN/)).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: /Заявка перевозчику/ })).not.toBeInTheDocument();
});
it("shows a permission failure without fallback rows or optimistic actions", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({}, { status: 403 })); vi.stubGlobal("fetch", fetcher);
  render(<OfficeView board={board} />); fireEvent.click(screen.getByRole("button", { name: "Доставка" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Недостаточно прав");
  expect(screen.queryByText("Нет доступных документов")).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("mounts the existing reviewer queue only on its tab and preserves the document funnel", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher); render(<OfficeView board={board} />);
  expect(screen.queryByText("Назначения проверяющих")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Проверяющие" })); expect(screen.getByText("Назначения проверяющих")).toBeInTheDocument();
  expect(screen.getByText("Нативная воронка документов").parentElement?.className).toBe("hidden"); expect(fetcher).not.toHaveBeenCalled();
});
