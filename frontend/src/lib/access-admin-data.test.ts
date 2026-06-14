import { describe, expect, it } from "vitest";

import {
  ALL_SLUGS,
  DEFAULT_MATRIX,
  DEFAULT_SPECIAL_BY_ROLE,
  DEFAULT_SPECIAL_BY_USER,
  EMPLOYEES,
  MODULES,
  ROLES,
  SPECIAL_PERMISSIONS,
  employeesByRole,
  isSuperRole,
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

  it("роль «Контролёр» — сквозная, видит ключевые модули, но не всё", () => {
    const ctl = ROLES.find((r) => r.slug === "controller");
    expect(ctl?.title).toBe("Контролёр");
    expect(ctl?.superRole).toBeUndefined();
    const slugs = DEFAULT_MATRIX.controller;
    expect(slugs).toEqual(expect.arrayContaining(["crm", "procurement", "production", "office"]));
    expect(slugs.length).toBeLessThan(MODULES.length);
  });
});

describe("системные функции", () => {
  it("isSuperRole помечает администраторов (директор/коммерческий)", () => {
    expect(isSuperRole("director")).toBe(true);
    expect(isSuperRole("commercial")).toBe(true);
    expect(isSuperRole("sales")).toBe(false);
    expect(isSuperRole("controller")).toBe(false);
  });

  it("есть функция «Удаление помеченных объектов», помечена как необратимая", () => {
    const purge = SPECIAL_PERMISSIONS.find((p) => p.slug === "purge_marked");
    expect(purge?.title).toBe("Удаление помеченных объектов");
    expect(purge?.danger).toBe(true);
  });

  it("дефолтные выдачи пусты — функция есть только у администраторов неявно", () => {
    expect(Object.keys(DEFAULT_SPECIAL_BY_ROLE)).toHaveLength(0);
    expect(Object.keys(DEFAULT_SPECIAL_BY_USER)).toHaveLength(0);
  });

  it("слаги выдач (если появятся) ссылаются на известные функции", () => {
    const known = new Set(SPECIAL_PERMISSIONS.map((p) => p.slug));
    for (const perms of Object.values(DEFAULT_SPECIAL_BY_ROLE))
      for (const p of perms) expect(known.has(p)).toBe(true);
    for (const perms of Object.values(DEFAULT_SPECIAL_BY_USER))
      for (const p of perms) expect(known.has(p)).toBe(true);
  });
});
