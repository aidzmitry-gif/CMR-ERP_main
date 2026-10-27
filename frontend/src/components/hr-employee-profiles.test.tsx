import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { HrEmployeeProfiles } from "./hr-employee-profiles";

vi.mock("@/components/employee-profile-form", () => ({ EmployeeProfileForm: () => <div>Личная анкета</div> }));
const employee = { id: 1, full_name: "Иванов Иван", position: "Менеджер", department: "Продажи", status: "active", profile_status: "not_started" };
const request = vi.fn();
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", request); });
async function openForm(name = "Петров Пётр") {
  await screen.findByText("Иванов Иван");
  fireEvent.click(screen.getByRole("button", { name: "Добавить сотрудника" }));
  fireEvent.change(screen.getByLabelText("ФИО"), { target: { value: name } });
  fireEvent.change(screen.getByLabelText("Должность"), { target: { value: " Кладовщик " } });
  fireEvent.change(screen.getByLabelText("Отдел"), { target: { value: " Склад " } });
}

it("shows employment separately from private profile and links the actual hiring workflow", async () => {
  request.mockResolvedValue(response([employee]));
  render(<HrEmployeeProfiles canReadPrivate={false} />);
  await screen.findByText("Иванов Иван");
  expect(screen.getByText("Работает")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Открыть анкету" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Добавить сотрудника" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "подбор персонала" })).toHaveAttribute("href", "/erp/hr");
  expect(screen.getByRole("link", { name: "приглашения сотрудников" })).toHaveAttribute("href", "/erp/settings/invitations?scope=erp");
});
it("creates a card through the existing API without an account or invitation", async () => {
  request.mockResolvedValueOnce(response([employee])).mockResolvedValueOnce(response({ ...employee, id: 2, full_name: "Петров Пётр" }, 201));
  render(<HrEmployeeProfiles canReadPrivate canCreate />);
  await openForm("  Петров   Пётр  ");
  fireEvent.click(screen.getByRole("button", { name: "Создать карточку" }));
  expect(await screen.findByText("Петров Пётр")).toBeInTheDocument();
  expect(request).toHaveBeenCalledTimes(2);
  expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ full_name: "Петров Пётр", position: "Кладовщик", department: "Склад", status: "active" });
  expect(screen.getByText(/Карточка сотрудника создана/)).toBeInTheDocument();
});
it("prevents a duplicate visible full name", async () => {
  request.mockResolvedValueOnce(response([employee]));
  render(<HrEmployeeProfiles canReadPrivate={false} canCreate />);
  await openForm(" иванов   Иван ");
  fireEvent.click(screen.getByRole("button", { name: "Создать карточку" }));
  expect(await screen.findByText(/Сотрудник с таким ФИО уже есть/)).toBeInTheDocument();
  expect(request).toHaveBeenCalledTimes(1);
});
it("blocks a retry after an unknown save until the operator refreshes the list", async () => {
  request.mockResolvedValueOnce(response([employee])).mockRejectedValueOnce(new TypeError("network"))
    .mockResolvedValueOnce(response([employee, { ...employee, id: 2, full_name: "Петров Пётр" }]));
  render(<HrEmployeeProfiles canReadPrivate={false} canCreate />);
  await openForm();
  fireEvent.click(screen.getByRole("button", { name: "Создать карточку" }));
  expect(await screen.findByText(/Результат сохранения неизвестен/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Создать карточку" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Обновить список" }));
  await screen.findByText("Петров Пётр");
  await waitFor(() => expect(screen.getByRole("button", { name: "Создать карточку" })).not.toBeDisabled());
  fireEvent.click(screen.getByRole("button", { name: "Создать карточку" }));
  expect(await screen.findByText(/Сотрудник с таким ФИО уже есть/)).toBeInTheDocument();
  expect(request).toHaveBeenCalledTimes(3);
});
it("reports denied loading rather than an empty employee registry", async () => {
  request.mockResolvedValue(response({}, 403));
  render(<HrEmployeeProfiles canReadPrivate={false} canCreate />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Проверьте доступ к HR");
  expect(screen.queryByText("Сотрудников пока нет.")).not.toBeInTheDocument();
});
