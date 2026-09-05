import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CrmStaffAccess } from "@/components/erp/crm-staff-access";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const staff = [{ employee_id: 7, full_name: "Иванов И.И.", department: "Продажи", position: "Менеджер", user_status: "active", role: "sales", allowed_roles: [{ slug: "sales", label: "Менеджер CRM" }, { slug: "sales_head", label: "РОП" }] }];
const response = (ok: boolean, body: unknown) => ({ ok, json: async () => body });

afterEach(() => { vi.restoreAllMocks(); refresh.mockReset(); });

describe("CrmStaffAccess", () => {
  it("создаёт только карточку CRM-сотрудника", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(true, { employee_id: 9 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<CrmStaffAccess staff={staff} />);
    fireEvent.change(screen.getByLabelText("ФИО"), { target: { value: "Петров П.П." } });
    fireEvent.click(screen.getByRole("button", { name: "Создать карточку" }));
    await screen.findByRole("status");
    expect(fetchMock).toHaveBeenCalledWith("/api/system/users/crm-staff", expect.objectContaining({ method: "POST", body: JSON.stringify({ full_name: "Петров П.П." }) }));
    expect(screen.getByText(/Учётная запись и письмо ещё не создаются/)).toBeInTheDocument();
  });

  it("отправляет смену роли после отдельного подтверждения и передаёт ожидаемую текущую роль", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(true, { employee_id: 7, role: "sales_head" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<CrmStaffAccess staff={staff} />);
    fireEvent.click(screen.getByRole("button", { name: "РОП" }));
    expect(await screen.findByRole("dialog", { name: "Подтвердите смену роли" })).toHaveTextContent("sales → РОП");
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith("/api/system/users/7/crm-role", expect.objectContaining({ method: "POST", body: JSON.stringify({ role: "sales_head", expected_current_role: "sales" }) }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("меняет видимость сделок отдельно от роли и передаёт ожидаемую видимость", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(true, { employee_id: 7, deal_visibility: "own" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<CrmStaffAccess staff={staff} />);

    fireEvent.click(screen.getByRole("button", { name: "Только свои сделки" }));
    const dialog = await screen.findByRole("dialog", { name: "Подтвердите изменение видимости сделок" });
    expect(dialog).toHaveTextContent("Все сделки CRM → Только свои сделки");
    expect(dialog).toHaveTextContent("применится со следующего запроса сотрудника");
    expect(dialog).toHaveTextContent("Сделки без назначенного владельца будут скрыты");
    expect(dialog).toHaveTextContent("лиды, сервис, Client 360, звонки и согласования");
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith("/api/system/users/7/crm-visibility", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ deal_visibility: "own", expected_current_visibility: "all" }),
    }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("не позволяет менять роль или видимость до активации", () => {
    render(<CrmStaffAccess staff={[{
      employee_id: 8,
      full_name: "Новый сотрудник",
      department: "Продажи",
      user_status: "onboarding",
      role: "onboarding",
      allowed_roles: [{ slug: "sales", label: "Менеджер CRM" }],
    }]} />);

    expect(screen.getByRole("button", { name: "Менеджер CRM" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "✓ Все сделки CRM" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Только свои сделки" })).toBeDisabled();
  });

  it("блокирует изменение при незавершённой смене роли, даже если старая роль сохранена", () => {
    render(<CrmStaffAccess staff={[{
      ...staff[0],
      user_status: "role_changing",
    }]} />);

    expect(screen.getByText(/смена роли: требуется сверка/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "РОП" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Только свои сделки" })).toBeDisabled();
  });

  it("не сообщает об отказе, когда результат смены роли неизвестен из-за транспорта", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    render(<CrmStaffAccess staff={staff} />);

    fireEvent.click(screen.getByRole("button", { name: "РОП" }));
    await screen.findByRole("dialog", { name: "Подтвердите смену роли" });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Результат смены роли не подтверждён"));
    expect(screen.getByRole("alert")).toHaveTextContent("повторную отправку выполняйте только после сверки");
    expect(screen.getByRole("alert")).not.toHaveTextContent("войдите с правами руководителя");
  });
});
