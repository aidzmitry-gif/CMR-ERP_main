import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

// Компонент — чистый client-компонент с внутренними demo-данными (бэкенда по экрану
// пока нет): нет @/lib/api, нет next/navigation. formatByn — реальный (валюта BYN).
import { DocsArchive } from "@/components/docs/docs-archive";
import { formatByn } from "@/lib/format";

// сумма всех 6 помеченных: 12400+45000+86000+31000+240000+19800
const TOTAL = 12_400 + 45_000 + 86_000 + 31_000 + 240_000 + 19_800;

/** Вернуть DOM-контейнер группы отдела по его заголовку. */
function deptGroup(dept: string): HTMLElement {
  // заголовок отдела — span внутри шапки; корневой div группы — предок с рамкой
  const head = screen.getByText(dept).closest("div") as HTMLElement;
  return head.parentElement as HTMLElement; // шапка → корневой div группы (шапка + строки)
}

describe("DocsArchive", () => {
  it("рендерит заголовок, гейт доступа архивариуса и demo-строки", () => {
    render(<DocsArchive />);
    expect(screen.getByRole("heading", { name: /Архив документов/ })).toBeInTheDocument();
    // гейт доступа: роль doc_admin и вошедший архивариус
    expect(screen.getByText(/роль: doc_admin/)).toBeInTheDocument();
    expect(screen.getAllByText(/Архивариус · Кузнецова Л\./).length).toBeGreaterThan(0);
    // конкретные помеченные документы из demo-данных
    expect(screen.getByText(/Счёт СЧ-0461/)).toBeInTheDocument();
    expect(screen.getByText(/Договор ДГ-0120 — тендер РУП/)).toBeInTheDocument();
  });

  it("скорборд: количество и сумма помеченных в BYN, ИИ-плитки пусты до проверки", () => {
    render(<DocsArchive />);
    // плитка «помечено на удаление» = 6
    const countTile = screen.getByText("помечено на удаление").parentElement as HTMLElement;
    expect(countTile.textContent).toContain("6");
    // плитка «сумма помеченных» = formatByn(TOTAL) в BYN (форматтер даёт узкий nbsp —
    // сверяем по цифрам без пробелов, чтобы не завязываться на код разделителя разрядов)
    const sumTile = screen.getByText("сумма помеченных").parentElement as HTMLElement;
    const digitsOnly = (s: string) => s.replace(/\D/g, "");
    expect(sumTile.textContent).toContain("BYN");
    expect(digitsOnly(sumTile.textContent ?? "")).toContain(digitsOnly(formatByn(TOTAL)));
    // ИИ ещё не проверял → две плитки с прочерком
    expect(screen.getAllByText("ИИ ещё не проверял").length).toBe(2);
    // строки помечены «Не проверено» пока ИИ не отработал (по одной на 6 док.)
    expect(screen.getAllByText("Не проверено")).toHaveLength(6);
  });

  it("ИИ-проверка проставляет вердикты, обновляет плитки и блокирует кнопку", () => {
    render(<DocsArchive />);
    const runBtn = screen.getByRole("button", { name: /Проверить причины/ });
    fireEvent.click(runBtn);

    // 4 безопасных (safe) и 2 на разбор (risk) в demo-данных
    expect(screen.getAllByText("Можно удалять")).toHaveLength(4);
    expect(screen.getAllByText("Разобраться")).toHaveLength(2);
    // тост подтверждает итог проверки
    expect(screen.getByText(/ИИ проверил основания: 4 безопасных, 2 на разбор/)).toBeInTheDocument();
    // кнопка стала «Проверено» и задизейблена (повторно не запустить)
    const doneBtn = screen.getByRole("button", { name: /Проверено/ });
    expect(doneBtn).toBeDisabled();
    // плитки «Не проверено» больше нет
    expect(screen.queryByText("Не проверено")).not.toBeInTheDocument();
  });

  it("«Восстановить» убирает документ из списка, пишет тост и запись в журнал аудита", () => {
    render(<DocsArchive />);
    // журнал стартует с 3 записей
    const journalBadge = screen.getByText("Журнал аудита").parentElement as HTMLElement;
    expect(within(journalBadge).getByText("3")).toBeInTheDocument();
    expect(screen.getByText(/Счёт СЧ-0461/)).toBeInTheDocument();

    // восстановить первый документ — его строка «Восстановить»
    const restoreButtons = screen.getAllByRole("button", { name: "Восстановить" });
    expect(restoreButtons).toHaveLength(6);
    fireEvent.click(restoreButtons[0]);

    // одна строка ушла из списка помеченных (имя переезжает в тост+журнал, поэтому
    // «исчезновение» проверяем по числу строковых кнопок, а не по имени документа)
    expect(screen.getAllByRole("button", { name: "Восстановить" })).toHaveLength(5);
    // тост восстановления
    expect(screen.getByText(/Восстановлено:/)).toBeInTheDocument();
    // журнал вырос до 4 (добавлена запись restore)
    expect(within(journalBadge).getByText("4")).toBeInTheDocument();
  });

  it("«Удалить» безвозвратно убирает документ и логирует «удалён безвозвратно»", () => {
    render(<DocsArchive />);
    const before = screen.getAllByText("удалён безвозвратно").length; // 1 запись в стартовом журнале
    const target = screen.getByText(/КП-0288 — годовая поставка/);
    expect(target).toBeInTheDocument();

    // строковые кнопки «Удалить» (не «Удалить отмеченные» в шапках отделов)
    const purgeButtons = screen.getAllByRole("button", { name: "Удалить" });
    expect(purgeButtons).toHaveLength(6);
    // удаляем именно строку КП-0288: находим её кнопку в пределах строки
    // (span-имя → flex → min-w-0 → grid-строка)
    const row = target.parentElement?.parentElement?.parentElement as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Удалить" }));

    // строка ушла (5 строковых кнопок «Удалить» осталось; имя живёт в тосте/журнале)
    expect(screen.getAllByRole("button", { name: "Удалить" })).toHaveLength(5);
    // в журнале появилась ещё одна запись «удалён безвозвратно»
    expect(screen.getAllByText("удалён безвозвратно").length).toBe(before + 1);
    expect(screen.getByText(/Удалено безвозвратно:/)).toBeInTheDocument();
  });

  it("групповое удаление отдела: отметка отдела включает кнопку, клик чистит группу и пишет «удалено группой»", () => {
    render(<DocsArchive />);
    const dept = "Отдел продаж · Новые"; // 3 документа в demo
    const group = deptGroup(dept);

    // кнопка группового удаления сначала задизейблена (ничего не отмечено)
    const purgeDeptBtn = within(group).getByRole("button", { name: /Удалить отмеченные/ });
    expect(purgeDeptBtn).toBeDisabled();

    // отметить весь отдел — первый чекбокс в шапке группы
    const deptCheckbox = within(group).getAllByRole("checkbox")[0];
    fireEvent.click(deptCheckbox);

    // кнопка стала активной и показывает счётчик (3)
    const activeBtn = within(group).getByRole("button", { name: /Удалить отмеченные \(3\)/ });
    expect(activeBtn).not.toBeDisabled();
    fireEvent.click(activeBtn);

    // все 3 документа отдела ушли — заголовок отдела больше не рендерится
    expect(screen.queryByText(dept)).not.toBeInTheDocument();
    // тост и запись «удалено группой» в журнале
    expect(screen.getByText(/Удалено группой: 3 док\./)).toBeInTheDocument();
    expect(screen.getAllByText("удалено группой").length).toBeGreaterThan(0);
  });

  it("после ИИ-проверки чекбокс «отметить всё, что ИИ разрешил» выбирает только безопасные", () => {
    render(<DocsArchive />);
    fireEvent.click(screen.getByRole("button", { name: /Проверить причины/ }));

    const safeCheckbox = screen.getByRole("checkbox", {
      name: /отметить всё, что ИИ разрешил удалять/,
    });
    fireEvent.click(safeCheckbox);
    expect((safeCheckbox as HTMLInputElement).checked).toBe(true);

    // «Отдел продаж · Новые» целиком безопасный (3 safe) → кнопка удаления показывает (3)
    const newDept = deptGroup("Отдел продаж · Новые");
    expect(
      within(newDept).getByRole("button", { name: /Удалить отмеченные \(3\)/ }),
    ).not.toBeDisabled();

    // «Тендерный отдел» содержит только risk-документ → в нём ничего не отмечено
    const tender = deptGroup("Тендерный отдел");
    expect(
      within(tender).getByRole("button", { name: "Удалить отмеченные" }),
    ).toBeDisabled();
  });
});
