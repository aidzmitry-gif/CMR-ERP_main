export type EmployeeProfile = {
  employee_id: number;
  full_name: string;
  department: string;
  position: string;
  birth_date: string | null;
  phone: string;
  city: string;
  education: string;
  children_birth_dates: string[] | null;
  status: string;
  revision: number;
};

export const PROFILE_STATUSES: Record<string, string> = {
  not_started: "Не заполнена", draft: "Черновик", submitted: "Сотрудник заполнил",
};

/** Compare calendar dates; parsing UTC midnight shifts birthdays in some zones. */
export function ageOn(birthday: string, today = new Date()): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(birthday);
  if (!match) return null;
  const [, y, m, d] = match.map(Number);
  const date = new Date(y, m - 1, d);
  if (date.getFullYear() !== y || date.getMonth() !== m - 1 || date.getDate() !== d) return null;
  let age = today.getFullYear() - y;
  if (today.getMonth() + 1 < m || (today.getMonth() + 1 === m && today.getDate() < d)) age--;
  return age >= 0 ? age : null;
}
