"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { DIRECTORY_PAGE_SIZE, loadDirectory, type DirectoryKind, type DirectoryResult } from "@/lib/crm-directory";

export function CrmDirectory({ kind }: { kind: DirectoryKind }) {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState({ q: "", offset: 0, revision: 0 });
  const [loaded, setLoaded] = useState<{ key: string; result: DirectoryResult } | null>(null);
  const key = JSON.stringify([kind, query]);
  const result = loaded?.key === key ? loaded.result : null;
  const isContacts = kind === "contacts";
  const title = isContacts ? "Контакты" : "Клиенты";

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    void loadDirectory(kind, query.q, query.offset, controller.signal).then((next) => {
      if (current) setLoaded({ key, result: next });
    });
    return () => { current = false; controller.abort(); };
  }, [kind, query.q, query.offset, key]);

  function search(event: FormEvent) {
    event.preventDefault();
    setQuery((previous) => ({ q: draft.trim(), offset: 0, revision: previous.revision + 1 }));
  }

  function refresh() {
    setQuery((previous) => ({ ...previous, revision: previous.revision + 1 }));
  }

  return (
    <section className="space-y-5 p-4 md:p-6" aria-label={title}>
      <div>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        <p className="mt-1 text-sm text-muted">Показаны доступные вам записи. Работу с клиентом можно продолжить в его сделке.</p>
      </div>
      <form onSubmit={search} className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm text-muted">
          {isContacts ? "Имя, компания, телефон или email" : "Название или УНП"}
          <input value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={120}
            className="h-10 rounded-lg border border-line bg-surface px-3 text-ink" type="search" />
        </label>
        <button type="submit" className="h-10 rounded-lg border border-line px-4 text-sm text-ink hover:bg-sunken">Найти</button>
        <button type="button" onClick={refresh} disabled={!result}
          className="h-10 rounded-lg border border-line px-4 text-sm text-ink disabled:opacity-50">Обновить</button>
      </form>
      {!result && <p role="status" className="text-sm text-muted">{isContacts ? "Загрузка контактов…" : "Загрузка клиентов…"}</p>}
      {result && result.status !== "ok" && (
        <div role="alert" className="space-y-2 rounded-lg border border-line p-4 text-sm">
          <p>{result.status === "forbidden" ? "Доступ к этому списку запрещён."
            : result.status === "unauthorized" ? "Сессия истекла. Войдите в систему."
              : "Не удалось загрузить список. Повторите попытку."}</p>
          <button type="button" onClick={refresh} className="underline">Повторить</button>
        </div>
      )}
      {result?.status === "ok" && <>
        <p role="status" className="text-sm text-muted">Найдено: {result.total}</p>
        {result.rows.length === 0 ? <p className="text-sm text-muted">{query.q ? "По вашему запросу ничего не найдено." : "Нет доступных записей на этой странице."}</p> : (
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{title}</caption>
              <thead className="bg-sunken text-muted"><tr>
                <th scope="col" className="p-3">{isContacts ? "Контакт" : "Клиент"}</th>
                <th scope="col" className="p-3">{isContacts ? "Компания" : "УНП"}</th>
                {isContacts && <th scope="col" className="p-3">Связь</th>}
                <th scope="col" className="p-3">Сделка</th>
              </tr></thead>
              <tbody>{result.rows.map((row) => <tr key={row.id} className="border-t border-line">
                <td className="p-3 font-medium text-ink">
                  {"full_name" in row ? row.full_name : row.name}
                  {"is_primary" in row && row.is_primary && <span className="ml-2 text-xs text-muted">Основной</span>}
                  {"is_active" in row && !row.is_active && <span className="ml-2 text-xs text-muted">Архив</span>}
                </td>
                <td className="p-3 text-muted">{"counterparty_name" in row ? row.counterparty_name : row.unp ?? "Не указан"}</td>
                {"full_name" in row && <td className="p-3 text-muted"><div>{row.phone ?? "Телефон не указан"}</div><div>{row.email ?? "Email не указан"}</div></td>}
                <td className="p-3">{row.deal_id === null ? <span className="text-muted">Нет доступной ссылки</span>
                  : <Link className="whitespace-nowrap underline" href={`/crm/deals/${row.deal_id}`}>Открыть сделку</Link>}</td>
              </tr>)}</tbody>
            </table>
          </div>
        )}
        <nav aria-label="Страницы списка" className="flex items-center gap-3 text-sm">
          <button type="button" disabled={query.offset === 0} className="rounded-lg border border-line px-3 py-2 disabled:opacity-50"
            onClick={() => setQuery((previous) => ({ ...previous, offset: Math.max(0, previous.offset - DIRECTORY_PAGE_SIZE) }))}>Назад</button>
          <span>Страница {Math.floor(query.offset / DIRECTORY_PAGE_SIZE) + 1}</span>
          <button type="button" disabled={query.offset + DIRECTORY_PAGE_SIZE >= result.total} className="rounded-lg border border-line px-3 py-2 disabled:opacity-50"
            onClick={() => setQuery((previous) => ({ ...previous, offset: previous.offset + DIRECTORY_PAGE_SIZE }))}>Далее</button>
        </nav>
      </>}
    </section>
  );
}
