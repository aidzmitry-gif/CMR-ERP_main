import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmployeeInvitationForm } from "@/components/erp/employee-invitation-form";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const catalog = { departments: { "Продажи": ["sales", "sales_head", "sales_cli"] } };

function response(ok: boolean, body: unknown, status = ok ? 200 : 422) {
  return { ok, status, json: async () => body };
}

function fillForm() {
  fireEvent.change(screen.getByLabelText("ID сотрудника из HR"), { target: { value: "1350585" } });
  fireEvent.change(screen.getByLabelText("Рабочий email"), { target: { value: "lead@microchips.by" } });
  fireEvent.change(screen.getByLabelText("Отдел из HR"), { target: { value: "Продажи" } });
  fireEvent.change(screen.getByLabelText("Целевая рабочая роль"), { target: { value: "sales_head" } });
}

afterEach(() => {
  vi.restoreAllMocks();
  refresh.mockReset();
});

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
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("показывает понятную ошибку backend и не открывает подтверждение", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(false, { detail: "Отдел не совпадает с HR" })));
    render(<EmployeeInvitationForm departments={catalog.departments} />);

    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Проверить и продолжить" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Не удалось проверить данные приглашения"));
    expect(screen.getByRole("alert")).not.toHaveTextContent("Отдел не совпадает с HR");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("в CRM-режиме выбирает сотрудника по имени и не создаёт новую HR-карточку", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(true, {
      employee_id: 7,
      full_name: "Иванов Иван",
      username: "ivanov",
      email: "ivanov@belakb.by",
      department: "Продажи",
      role: "sales",
      ready: true,
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <EmployeeInvitationForm
        departments={catalog.departments}
        crmFlow
        crmStaff={[{ employee_id: 7, full_name: "Иванов Иван", department: "Продажи", position: "Менеджер", email: "ivanov@belakb.by" }]}
      />,
    );

    fireEvent.change(screen.getByLabelText("Сотрудник отдела CRM"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Целевая рабочая роль"), { target: { value: "sales" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить и продолжить" }));

    await screen.findByRole("dialog", { name: "Подтвердите отправку" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/system/users/preflight");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ employee_id: 7, email: "ivanov@belakb.by", department: "Продажи", role: "sales" });
  });

  it("в CRM-режиме создаёт HR-карточку только при проверке, затем выполняет preflight без отправки письма", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(true, { employee_id: 12, full_name: "Петров Пётр" }, 201))
      .mockResolvedValueOnce(response(true, {
        employee_id: 12,
        full_name: "Петров Пётр",
        username: "petrov",
        email: "petrov@belakb.by",
        department: "Продажи",
        role: "sales_cli",
        ready: true,
      }));
    vi.stubGlobal("fetch", fetchMock);
    render(<EmployeeInvitationForm departments={{}} crmFlow />);

    fireEvent.change(screen.getByLabelText("ФИО нового сотрудника"), { target: { value: "Петров Пётр" } });
    fireEvent.change(screen.getByLabelText("Рабочий email"), { target: { value: "petrov@belakb.by" } });
    fireEvent.change(screen.getByLabelText("Целевая рабочая роль"), { target: { value: "sales_cli" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить и продолжить" }));

    await screen.findByRole("dialog", { name: "Подтвердите отправку" });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/system/users/crm-staff",
      "/api/system/users/preflight",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ full_name: "Петров Пётр" });
    expect(fetchMock.mock.calls.map((call) => call[0])).not.toContain("/api/system/users/invite");
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
    expect(screen.queryByRole("button", { name: "Активировать" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Рабочий доступ сотрудника #1350585 активирован.");
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("не показывает технический код ошибки и выводит понятный статус", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(false, { detail: "keycloak_invite_email_failed" }, 502)));
    render(<EmployeeInvitationForm departments={catalog.departments} />);

    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Проверить и продолжить" }));

    await screen.findByRole("alert");
    expect(screen.getByRole("alert")).toHaveTextContent("Письмо-приглашение не было подтверждено");
    expect(screen.getByRole("alert")).not.toHaveTextContent("keycloak_invite_email_failed");
  });

  it("показывает read-only журнал операций без технических ключей", () => {
    render(
      <EmployeeInvitationForm
        departments={catalog.departments}
        canActivate
        invitationOperations={[{
          operation_kind: "invite",
          request_id: 42,
          employee_id: 1350585,
          full_name: "Кадурин Артем Юрьевич",
          email: "lead@microchips.by",
          username: "kadurin",
          target_department: "Продажи",
          target_role: "sales_head",
          status: "failed",
          error_code: "keycloak_invite_email_failed",
          created_at: "2026-09-01T10:00:00Z",
          completed_at: "2026-09-01T10:01:00Z",
          requires_reconciliation: true,
        }]}
      />,
    );

    expect(screen.getByRole("list", { name: "Журнал операций приглашений" })).toHaveTextContent("Кадурин Артем Юрьевич");
    expect(screen.getByRole("status")).toHaveTextContent("Требуется ручная сверка статуса");
    expect(screen.getByText(/Письмо-приглашение не было подтверждено/)).toBeInTheDocument();
    expect(screen.queryByText(/erp-invite-/)).not.toBeInTheDocument();
  });

  it("закрывает подтверждение Escape и возвращает фокус на кнопку проверки", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(true, {
      employee_id: 1350585,
      full_name: "Кадурин Артем Юрьевич",
      username: "kadurin",
      email: "lead@microchips.by",
      department: "Продажи",
      role: "sales_head",
      ready: true,
    })));
    render(<EmployeeInvitationForm departments={catalog.departments} />);
    fillForm();
    const trigger = screen.getByRole("button", { name: "Проверить и продолжить" });
    fireEvent.click(trigger);
    await screen.findByRole("dialog", { name: "Подтвердите отправку" });
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });
});
