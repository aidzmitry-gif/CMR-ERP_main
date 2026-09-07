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
  it("prepares a new director through HR and sends only after confirmation", async () => {
    const payload = { employee_id: 17, full_name: "Тестовый руководитель", email: "director@example.com", username: "test-director", department: "Руководство", role: "director", ready: true };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(true, { id: 17 }, 201))
      .mockResolvedValueOnce(response(true, payload))
      .mockResolvedValueOnce(response(true, { ...payload, role: "onboarding", expected_role: "director", expected_department: "Руководство", status: "invited" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    render(<EmployeeInvitationForm generalFlow departments={{ Руководство: ["director"], Продажи: ["sales"] }} />);
    fireEvent.change(screen.getByLabelText("ФИО нового сотрудника"), { target: { value: payload.full_name } });
    fireEvent.change(screen.getByLabelText("Рабочий email"), { target: { value: payload.email } });
    fireEvent.change(screen.getByLabelText("Отдел из HR"), { target: { value: "Руководство" } });
    fireEvent.change(screen.getByLabelText("Целевая рабочая роль"), { target: { value: "director" } });
    expect(screen.getByRole("option", { name: "Директор" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Проверить и продолжить" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("director");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/hr/employees", "/api/system/users/preflight"]);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ full_name: payload.full_name, department: "Руководство", status: "active" });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ employee_id: 17, department: "Руководство", role: "director" });
    fireEvent.click(screen.getByRole("button", { name: "Отправить приглашение" }));
    await screen.findByText("Приглашение отправлено");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/system/users/invite");
    expect(fetchMock.mock.calls[2][1].headers["Idempotency-Key"]).toMatch(/^erp-invite-/);
  });

  it("keeps an existing HR department fixed and resets role on employee changes", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(true, { ready: true, employee_id: 17, full_name: "Тест", email: "director@example.com", department: "Руководство", role: "director" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<EmployeeInvitationForm generalFlow departments={{ Руководство: ["director"], Продажи: ["sales"] }} crmStaff={[
      { employee_id: 17, full_name: "Тест", department: "Руководство" },
      { employee_id: 18, full_name: "Продажи тест", department: "Продажи" },
    ]} />);
    fireEvent.change(screen.getByLabelText("Сотрудник"), { target: { value: "17" } });
    expect(screen.getByLabelText("Отдел из HR")).toBeDisabled();
    expect(screen.getByLabelText("Отдел из HR")).toHaveValue("Руководство");
    fireEvent.change(screen.getByLabelText("Целевая рабочая роль"), { target: { value: "director" } });
    fireEvent.change(screen.getByLabelText("Рабочий email"), { target: { value: "director@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить и продолжить" }));
    await screen.findByRole("dialog");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/system/users/preflight");
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.change(screen.getByLabelText("Сотрудник"), { target: { value: "18" } });
    expect(screen.getByLabelText("Целевая рабочая роль")).toHaveValue("");
    expect(screen.queryByRole("option", { name: "Директор" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Рабочий email")).toHaveValue("");
  });

  it("does not repeat an uncertain general HR creation or send an invitation", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("connection lost"));
    vi.stubGlobal("fetch", fetchMock);
    render(<EmployeeInvitationForm generalFlow departments={{ Руководство: ["director"] }} />);
    fireEvent.change(screen.getByLabelText("ФИО нового сотрудника"), { target: { value: "Тест" } });
    fireEvent.change(screen.getByLabelText("Рабочий email"), { target: { value: "director@example.com" } });
    fireEvent.change(screen.getByLabelText("Отдел из HR"), { target: { value: "Руководство" } });
    fireEvent.change(screen.getByLabelText("Целевая рабочая роль"), { target: { value: "director" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить и продолжить" }));
    await screen.findByText(/Результат создания карточки неизвестен/);
    expect(screen.getByRole("button", { name: "Проверить и продолжить" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

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

  it("не продолжает приглашение после отказа в создании CRM-сотрудника", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(false, { detail: "forbidden" }, 403));
    vi.stubGlobal("fetch", fetchMock);
    render(<EmployeeInvitationForm departments={{}} crmFlow />);

    fireEvent.change(screen.getByLabelText("ФИО нового сотрудника"), { target: { value: "Петров Пётр" } });
    fireEvent.change(screen.getByLabelText("Рабочий email"), { target: { value: "petrov@belakb.by" } });
    fireEvent.change(screen.getByLabelText("Целевая рабочая роль"), { target: { value: "sales" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить и продолжить" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("нет прав для создания или проверки приглашения"));
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(["/api/system/users/crm-staff"]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("скрывает форму, если сервер не подтвердил доступ к приглашениям", () => {
    render(<EmployeeInvitationForm departments={catalog.departments} accessError="Недостаточно прав для приглашений." />);

    expect(screen.getByRole("alert")).toHaveTextContent("Недостаточно прав для приглашений.");
    expect(screen.queryByRole("button", { name: "Проверить и продолжить" })).not.toBeInTheDocument();
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
