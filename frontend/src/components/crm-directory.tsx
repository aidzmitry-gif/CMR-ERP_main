"use client";

import Link from "next/link";
import { CreateCrmClient } from "@/components/create-crm-client";
import { SpravCounterpartyEditor } from "@/components/erp/spravochniki/sprav-counterparty-editor";
import { useEffect, useState, type FormEvent } from "react";
import { DIRECTORY_PAGE_SIZE, loadDirectory, responsibleManagerText, type DirectoryKind, type DirectoryResult } from "@/lib/crm-directory";

export function CrmDirectory({ kind }: { kind: DirectoryKind }) {
  const [draft, setDraft] = useState("");
  const [creating, setCreating] = useState<{ kind: "client" } | { kind: "registry"; unp: string } | null>(null);
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
        <p className="mt-1 text-sm text-muted">Показаны доступные вам записи. Нажмите на название компании, чтобы открыть её карточку.</p>
      </div>
      {!isContacts && (creating?.kind === "registry" ? <div className="min-w-0 space-y-3">
        <p className="text-sm text-muted">Создаётся карточка контрагента в справочнике. Она появится в списке клиентов CRM. Введите УНП, получите сведения МНС и отметьте реквизиты для сохранения.</p>
        <SpravCounterpartyEditor mode="create" embedded initialUnp={creating.unp} onCancel={() => setCreating(null)} />
      </div> : creating?.kind === "client" ? <CreateCrmClient onCancel={() => setCreating(null)} onCreated={(name) => {
        setCreating(null);
        setDraft(name);
        setQuery((previous) => ({ q: name, offset: 0, revision: previous.revision + 1 }));
      }} /> : <div className="space-y-2">
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setCreating({ kind: "client" })} className="rounded-lg bg-accent px-4 py-2 text-sm text-white">Новый клиент</button>
          <button type="button" onClick={() => setCreating({ kind: "registry", unp: /^[0-9]{9}$/.test(draft.trim()) ? draft.trim() : "" })} className="rounded-lg border border-accent px-4 py-2 text-sm text-accent">Создать по УНП</button>
        </div>
        <p className="text-sm text-muted">По УНП можно получить наименование, юридический адрес и статус из МНС. Реквизиты проверяются перед сохранением.</p>
      </div>)}
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
                {!isContacts && <th scope="col" className="p-3">Ответственный менеджер</th>}
                <th scope="col" className="p-3">Сделка</th>
              </tr></thead>
              <tbody>{result.rows.map((row) => <tr key={`${"source" in row ? row.source : "mdm"}:${row.id}`} className="border-t border-line">
                <td className="p-3 font-medium text-ink">
                  {"full_name" in row
                    ? row.source === "crm" && row.crm_client_id != null
                      ? <Link className="underline" href={`/crm/clients/${row.crm_client_id}?contact=${row.id}#crm-contact-${row.id}`}>{row.full_name}</Link>
                      : row.source !== "crm" && row.counterparty_id != null
                        ? <Link className="underline" href={`/erp/spravochniki/counterparty/${row.counterparty_id}?contact=${row.id}#counterparty-contact-${row.id}`}>{row.full_name}</Link>
                        : <>{row.full_name}<span className="ml-2 text-xs text-muted">Контекст не связан</span></>
                    : row.source === "crm"
                      ? <Link className="underline" href={`/crm/clients/${row.id}`}>{row.name}</Link>
                      : <Link className="underline" href={`/erp/spravochniki/counterparty/${row.id}`}>{row.name}</Link>}
                  {"source" in row && row.source === "crm" && <span className="ml-2 text-xs text-muted">Создан в CRM</span>}
                  {"is_primary" in row && row.is_primary && <span className="ml-2 text-xs text-muted">Основной</span>}
                  {"is_active" in row && !row.is_active && <span className="ml-2 text-xs text-muted">Архив</span>}
                </td>
                <td className="p-3 text-muted">{"full_name" in row
                  ? row.source === "crm" && row.crm_client_id != null
                    ? <Link className="underline" href={`/crm/clients/${row.crm_client_id}`}>{row.counterparty_name ?? "CRM-клиент"}</Link>
                    : row.source !== "crm" && row.counterparty_id != null
                      ? <Link className="underline" href={`/erp/spravochniki/counterparty/${row.counterparty_id}`}>{row.counterparty_name ?? "Компания"}</Link>
                      : <span>Контекст не связан</span>
                  : row.unp ?? "Не указан"}</td>
                {"full_name" in row && <td className="p-3 text-muted"><div>{row.phone ?? "Телефон не указан"}</div><div>{row.email ?? "Email не указан"}</div></td>}
                {!("full_name" in row) && <td className="p-3">{responsibleManagerText(row.responsible_manager)}</td>}
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
