import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmployeeInvitationForm } from "@/components/erp/employee-invitation-form";

const catalog = { departments: { "Продажи": ["sales", "sales_head"] } };

function response(ok: boolean, body: unknown, status = ok ? 200 : 422) {
  return { ok, status, json: async () => body };
}

function fillForm() {
  fireEvent.change(screen.getByLabelText("ID сотрудника из HR"), { target: { value: "1350585" } });
  fireEvent.change(screen.getByLabelText("Рабочий email"), { target: { value: "lead@microchips.by" } });
  fireEvent.change(screen.getByLabelText("Отдел из HR"), { target: { value: "Продажи" } });
  fireEvent.change(screen.getByLabelText("Целевая рабочая роль"), { target: { value: "sales_head" } });
}

afterEach(() => vi.restoreAllMocks());

describe("EmployeeInvitationForm", () => {
  it("проверяет один конкретный ID и отправляет только после явного подтверждения", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(true, {
        employee_id: 1350585,
        full_name: "Кадурин Артем Юрьевич",
        username: "kadurin",
        email: "lead@microchips.by",
        department: "Продажи",
        role: "sales_head",
        ready: true,
      }))
      .mockResolvedValueOnce(response(true, {
        full_name: "Кадурин Артем Юрьевич",
        username: "kadurin",
        email: "lead@microchips.by",
        department: "Продажи",
        role: "onboarding",
        expected_department: "Продажи",
        expected_role: "sales_head",
        status: "invited",
      }, 201));
    vi.stubGlobal("fetch", fetchMock);
    render(<EmployeeInvitationForm departments={catalog.departments} />);

    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Проверить и продолжить" }));

    const dialog = await screen.findByRole("dialog", { name: "Подтвердите отправку" });
    expect(dialog).toHaveTextContent("onboarding");
    expect(dialog).toHaveTextContent("sales_head");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/system/users/preflight");

    fireEvent.click(screen.getByRole("button", { name: "Отправить приглашение" }));
    await screen.findByText("Приглашение отправлено");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/system/users/invite");
    expect(fetchMock.mock.calls[1][1].headers["Idempotency-Key"]).toMatch(/^erp-invite-/);
    expect(fetchMock.mock.calls.map((call) => call[0])).not.toContain("/api/system/users");
    expect(screen.getByText(/Продажи · sales_head/)).toBeInTheDocument();
  });

  it("показывает ошибку backend и не открывает подтверждение", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(false, { detail: "Отдел не совпадает с HR" })));
    render(<EmployeeInvitationForm departments={catalog.departments} />);

    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Проверить и продолжить" }));

    await waitFor(() => expect(screen.getByText("Отдел не совпадает с HR")).toBeInTheDocument());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("активирует только зафиксированную onboarding-заявку после отдельного подтверждения", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(true, { employee_id: 1350585, role: "sales_head", status: "active" }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <EmployeeInvitationForm
        departments={catalog.departments}
        canActivate
        pendingInvitations={[{
          employee_id: 1350585,
          full_name: "Кадурин Артем Юрьевич",
          email: "lead@microchips.by",
          status: "onboarding",
          role: "onboarding",
          expected_department: "Продажи",
          expected_role: "sales_head",
        }]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Активировать" }));
    expect(await screen.findByRole("dialog", { name: "Подтвердите активацию" })).toHaveTextContent("sales_head");
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Подтвердить активацию" }));
    await screen.findByText("Рабочий доступ сотрудника #1350585 активирован.");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/system/users/1350585/activate");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST" });
    expect(fetchMock.mock.calls[0][1].headers["Idempotency-Key"]).toMatch(/^erp-activate-/);
  });
});
