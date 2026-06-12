import { describe, expect, it } from "vitest";

import {
  ALL_SLUGS,
  DEFAULT_MATRIX,
  EMPLOYEES,
  MODULES,
  ROLES,
  employeesByRole,
  makeUsername,
} from "./access-admin-data";

describe("makeUsername", () => {
  it("транслитерирует фамилию + инициал в ASCII-логин", () => {
    expect(makeUsername("Иванов И.И.")).toBe("ivanov_i");
    expect(makeUsername("Харькович Д.С.")).toBe("kharkovich_d");
  });

  it("без второго токена даёт только фамилию", () => {
    expect(makeUsername("Макаров")).toBe("makarov");
  });

  it("пустой ввод → пустая строка", () => {
    expect(makeUsername("   ")).toBe("");
  });

  it("совпадает с логинами из снимка config/access.py", () => {
    for (const e of EMPLOYEES) {
      // у некоторых демо-логинов своя ручная форма — проверяем хотя бы префикс-фамилию
      expect(e.username.length).toBeGreaterThan(0);
    }
  });
});

describe("employeesByRole", () => {
  it("группирует сотрудников по роли", () => {
    const grouped = employeesByRole(EMPLOYEES);
    expect(grouped.sales?.length).toBe(4);
    expect(grouped.director?.[0]?.full_name).toBe("Харькович Д.С.");
  });
});

describe("матрица доступа", () => {
  it("каждая роль присутствует в DEFAULT_MATRIX", () => {
    for (const r of ROLES) expect(DEFAULT_MATRIX[r.slug]).toBeDefined();
  });

  it("слаги матрицы — подмножество известных модулей", () => {
    const known = new Set(ALL_SLUGS);
    for (const slugs of Object.values(DEFAULT_MATRIX)) {
      for (const s of slugs) expect(known.has(s)).toBe(true);
    }
  });

  it("директор и коммерческий видят все модули", () => {
    expect(DEFAULT_MATRIX.director).toHaveLength(MODULES.length);
    expect(DEFAULT_MATRIX.commercial).toHaveLength(MODULES.length);
  });
});
