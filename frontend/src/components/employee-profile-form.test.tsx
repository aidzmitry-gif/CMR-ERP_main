import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EmployeeProfileForm } from "./employee-profile-form";

const profile = { employee_id: 7, full_name: "Тестовый сотрудник", department: "Продажи", position: "Менеджер",
  birth_date: null, phone: "", city: "", education: "", children_birth_dates: null, status: "not_started", revision: 0 };
const response = (body: unknown, status = 200) => ({ ok: status === 200, status, json: async () => body });
afterEach(() => vi.restoreAllMocks());

describe("EmployeeProfileForm", () => {
  it("saves optional fields without sending employee identity or work roles", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValueOnce(response(profile) as Response)
      .mockResolvedValueOnce(response({ ...profile, city: "Минск", status: "submitted", revision: 1 }) as Response);
    render(<EmployeeProfileForm />);
    await screen.findByText("Тестовый сотрудник");
    fireEvent.change(screen.getByLabelText("Город проживания"), { target: { value: "Минск" } });
    fireEvent.click(screen.getByRole("button", { name: "Я заполнил карточку" }));
    await screen.findByText(/Карточка сохранена/);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/hr/me/profile");
    const body = JSON.parse(fetchMock.mock.calls[1][1]?.body as string);
    expect(body).toEqual({ birth_date: null, phone: "", city: "Минск", education: "", children_birth_dates: null, revision: 0, status: "submitted" });
  });
  it("shows failed loads and never exposes a blank writable replacement", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(response({}, 403) as Response);
    render(<EmployeeProfileForm />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа");
    expect(screen.queryByRole("button", { name: "Я заполнил карточку" })).not.toBeInTheDocument();
  });
  it("does not say saved when another tab changed the record", async () => {
    vi.spyOn(global, "fetch").mockResolvedValueOnce(response(profile) as Response).mockResolvedValueOnce(response({}, 409) as Response);
    render(<EmployeeProfileForm />);
    await screen.findByText("Тестовый сотрудник");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить черновик" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("другом окне"));
    expect(screen.queryByText(/Черновик сохранён/)).not.toBeInTheDocument();
  });
  it("HR can view but cannot submit another employee's profile", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(response(profile) as Response);
    render(<EmployeeProfileForm employeeId={7} />);
    await screen.findByText("Тестовый сотрудник");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/hr/employee-profiles/7");
    expect(screen.getByLabelText("Телефон")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Я заполнил карточку" })).not.toBeInTheDocument();
  });
});
