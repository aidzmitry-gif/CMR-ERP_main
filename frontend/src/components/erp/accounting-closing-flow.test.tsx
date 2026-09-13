import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingControls } from "./accounting-controls";

afterEach(() => vi.unstubAllGlobals());
it("locks month and evidence during uncertain closing while allowing exact retry", async () => {
  const month = new Date().toISOString().slice(0,7);
  const requests: string[] = [];
  const onChanged = vi.fn();
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    let data: unknown = [];
    if (url.endsWith("/catalog")) data = { version: "synthetic", accounts: [] };
    if (url.endsWith("/periods")) data = [{ month, generation: 2, closed: requests.length === 2 }];
    if (url.endsWith("/financial-closing-preview")) data = { organization_id: 1, month, policy_id: 3, status: "preview_only", confirmation_available: true, basis_digest: "a".repeat(64), period_generation: 2, monthly_lines: [], annual_lines: [] };
    if (url.endsWith("/financial-closing-confirm")) {
      requests.push(String(options?.body));
      if (requests.length === 1) throw new Error("lost response");
      data = { organization_id: 1, month, request_key: JSON.parse(requests[0]).request_key, closed: true, receipt_id: 8, digest: "b".repeat(64) };
    }
    return { ok: true, json: async () => data };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingControls org="1" initialSection="periods" onChanged={onChanged} />);
  for (const label of ["Полнота документов","Сверка банка","Сверка расчётов","Сверка склада","Себестоимость и затраты","Амортизация","Валютные операции","Налоги","Финансовый результат","Контрольная ОСВ"]) {
    fireEvent.change(await screen.findByLabelText(label), { target: { value: "Checked" } });
  }
  fireEvent.click(screen.getByText("Рассчитать перенос финансового результата"));
  fireEvent.click(await screen.findByText("Подтвердить переносы и закрыть месяц"));
  const retry = await screen.findByText("Проверить результат закрытия");
  expect(screen.getByLabelText("Месяц закрытия")).toBeDisabled();
  expect(screen.getByLabelText("Сверка банка")).toBeDisabled();
  expect(screen.getByText("Настройки книги")).toBeDisabled();
  expect(retry).not.toBeDisabled();
  fireEvent.click(retry);
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(requests).toHaveLength(2);
  expect(requests[0]).toBe(requests[1]);
  expect(await screen.findByText("Месяц закрыт с переносом финансового результата.")).toBeInTheDocument();
});
