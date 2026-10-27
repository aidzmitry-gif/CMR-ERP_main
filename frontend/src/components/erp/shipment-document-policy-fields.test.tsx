import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { ShipmentDocumentPolicyFields } from "./shipment-document-policy-fields";

it("requires explicit TN or TTN details before returning a policy scenario", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<ShipmentDocumentPolicyFields org="7" effectiveDate="2026-09-01" onChange={onChange} />);
  await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ scope: "7:2026-09-01", enabled: false, value: null }));
  await user.click(screen.getByLabelText("Настроить применимые сценарии ТН/ТТН"));
  await user.click(screen.getByLabelText("Настроить ТТН"));
  expect(onChange).toHaveBeenLastCalledWith({ scope: "7:2026-09-01", enabled: true, value: null });
  expect(screen.getByLabelText("ТТН — способ оформления")).toHaveValue("");
  await user.selectOptions(screen.getByLabelText("ТТН — способ оформления"), "electronic");
  await user.type(screen.getByLabelText("ТТН — версия формы"), "Форма v1");
  await user.type(screen.getByLabelText("ТТН — правило нумерации"), "Нумерация v1");
  await user.type(screen.getByLabelText("ТТН — правило подписания"), "Подписание v1");
  await user.type(screen.getByLabelText("ТТН — маршрут обмена"), "Оператор v1");
  await user.type(screen.getByLabelText("ТТН — доказательство"), "Приказ бухгалтера v1");
  await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({
    scope: "7:2026-09-01", enabled: true,
    value: { scenarios: [{ kind: "ttn", exchange_mode: "electronic", form_version: "Форма v1", numbering_rule: "Нумерация v1", signing_rule: "Подписание v1", exchange_rule: "Оператор v1", evidence: "Приказ бухгалтера v1" }] },
  }));
});
