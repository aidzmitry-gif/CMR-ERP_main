"use client";

import Link from "next/link";
import { Search } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  COUNTERPARTY_SEARCH_LIMIT,
  type CounterpartyRow,
  searchCounterparties,
} from "@/lib/reference-data";

interface Props {
  initialName?: string;
  initialUnp?: string;
}

type ViewState =
  | "idle"
  | "loading"
  | "success"
  | "invalid-query"
  | "unauthorized"
  | "forbidden"
  | "service-error";

interface Query {
  name: string;
  unp: string;
}

function normalizedQuery(name: string, unp: string): Query {
  return { name: name.trim(), unp: unp.trim() };
}

function queryKey(query: Query): string {
  return `${query.name}\u0000${query.unp}`;
}

function searchUrl(query: Query): string {
  const params = new URLSearchParams();
  if (query.name) params.set("name", query.name);
  if (query.unp) params.set("unp", query.unp);
  const encoded = params.toString();
  return `/erp/spravochniki/counterparty${encoded ? `?${encoded}` : ""}`;
}

function cardUrl(id: number, query: Query): string {
  const queryString = searchUrl(query).split("?")[1];
  return `/erp/spravochniki/counterparty/${encodeURIComponent(String(id))}${queryString ? `?${queryString}` : ""}`;
}

function statusText(state: ViewState): string {
  switch (state) {
    case "idle":
      return "Введите название или УНП и нажмите «Найти».";
    case "loading":
      return "Загрузка контрагентов…";
    case "invalid-query":
      return "Укажите только одно поле: название или УНП.";
    case "unauthorized":
      return "Сессия истекла или отсутствует авторизация (401).";
    case "forbidden":
      return "Доступ к справочнику контрагентов запрещён (403).";
    case "service-error":
      return "Сервис справочников недоступен или вернул некорректный ответ. Повторите попытку.";
    case "success":
      return "";
  }
}

export function SpravCounterparties({ initialName = "", initialUnp = "" }: Props) {
  const router = useRouter();
  const [name, setName] = useState(initialName);
  const [unp, setUnp] = useState(initialUnp);
  const initialQuery = normalizedQuery(initialName, initialUnp);
  const [state, setState] = useState<ViewState>(
    initialQuery.name || initialQuery.unp ? "loading" : "idle",
  );
  const [rows, setRows] = useState<CounterpartyRow[]>([]);
  const [submittedQuery, setSubmittedQuery] = useState<Query>(initialQuery);
  const requestVersion = useRef(0);
  const requestedQueryKey = useRef<string | null>(null);
  const propEffectVersion = useRef(0);

  const load = useCallback(async (query: Query) => {
    requestedQueryKey.current = queryKey(query);
    const version = ++requestVersion.current;
    setRows([]);
    setState("loading");
    const result = await searchCounterparties(query);
    if (requestVersion.current !== version) return;
    setState(result.status);
    setRows(result.status === "success" ? result.rows : []);
  }, []);

  useEffect(() => {
    const effectVersion = ++propEffectVersion.current;
    const query = normalizedQuery(initialName, initialUnp);
    const key = queryKey(query);
    const syncTimer = window.setTimeout(() => {
      if (propEffectVersion.current !== effectVersion) return;
      setName(initialName);
      setUnp(initialUnp);
      setSubmittedQuery(query);
    }, 0);
    if (requestedQueryKey.current === key) {
      return () => window.clearTimeout(syncTimer);
    }
    if (query.name || query.unp) {
      const requestTimer = window.setTimeout(() => {
        if (propEffectVersion.current !== effectVersion) return;
        void load(query);
      }, 0);
      return () => {
        window.clearTimeout(syncTimer);
        window.clearTimeout(requestTimer);
      };
    }
    requestedQueryKey.current = key;
    requestVersion.current += 1;
    const idleTimer = window.setTimeout(() => {
      if (propEffectVersion.current !== effectVersion) return;
      setRows([]);
      setState("idle");
    }, 0);
    return () => {
      window.clearTimeout(syncTimer);
      window.clearTimeout(idleTimer);
    };
  }, [initialName, initialUnp, load]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // A submit may happen before a props-sync timer from the previous URL fires.
    // Invalidate those callbacks so they cannot reset the new draft/results.
    propEffectVersion.current += 1;
    const query = normalizedQuery(name, unp);
    router.replace(searchUrl(query), { scroll: false });
    setSubmittedQuery(query);
    if (!query.name && !query.unp) {
      requestedQueryKey.current = queryKey(query);
      requestVersion.current += 1;
      setRows([]);
      setState("idle");
      return;
    }
    if (query.name && query.unp) {
      requestedQueryKey.current = queryKey(query);
      requestVersion.current += 1;
      setRows([]);
      setState("invalid-query");
      return;
    }
    void load(query);
  }

  return (
    <div className="mx-auto min-w-0 max-w-[1280px] space-y-4 p-6">
      <div className="rounded-2xl bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-bold text-ink">Контрагенты</h1>
            <p className="mt-1 text-sm text-muted">
              Поиск активных контрагентов по названию или УНП.
            </p>
          </div>
          <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
            максимум {COUNTERPARTY_SEARCH_LIMIT} результатов
          </span>
        </div>

        <form className="mt-4 space-y-3" onSubmit={submit}>
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,260px)_auto] md:items-end">
            <label className="block text-sm text-muted">
              Название
              <div className="mt-1 flex items-center gap-2 rounded-xl bg-sunken px-3 py-2">
                <Search className="h-3.5 w-3.5 shrink-0 text-faint" />
                <input
                  className="w-full bg-transparent text-ink outline-none placeholder:text-faint"
                  name="name"
                  placeholder="Например, Ромашка"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
            </label>
            <label className="block text-sm text-muted">
              УНП
              <input
                className="mt-1 w-full rounded-xl bg-sunken px-3 py-2 text-ink outline-none placeholder:text-faint"
                name="unp"
                inputMode="numeric"
                placeholder="9 цифр"
                value={unp}
                onChange={(event) => setUnp(event.target.value)}
              />
            </label>
            <button
              type="submit"
              className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
            >
              Найти
            </button>
          </div>
          <p className="text-[11px] text-faint">
            Пустой запрос не выгружает весь справочник. При достижении лимита уточните запрос.
          </p>
        </form>
      </div>

      <div className="rounded-2xl bg-surface shadow-card" aria-live="polite">
        {state !== "success" ? (
          <div className="px-5 py-8 text-center text-sm text-muted" role="status">
            {statusText(state)}
          </div>
        ) : rows.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-muted" role="status">
            Совпадений нет.
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3 text-sm text-muted">
              <span>Найдено: {rows.length}</span>
              <span className="text-[11px] text-faint">
                {rows.length >= COUNTERPARTY_SEARCH_LIMIT
                  ? `Показаны первые ${COUNTERPARTY_SEARCH_LIMIT}; уточните запрос для более точного результата.`
                  : `Лимит запроса: ${COUNTERPARTY_SEARCH_LIMIT}`}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
                    <th className="px-4 py-2 font-semibold">ID</th>
                    <th className="px-4 py-2 font-semibold">Название</th>
                    <th className="px-4 py-2 font-semibold">УНП</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {rows.map((row) => (
                    <tr key={row.id} className="hover:bg-sunken/60">
                      <td className="px-4 py-2.5 font-mono text-[12px] text-muted">
                        <Link
                          href={cardUrl(row.id, submittedQuery)}
                          className="text-accent hover:underline"
                        >
                          {row.id}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 text-ink">{row.name}</td>
                      <td className="px-4 py-2.5 font-mono text-[12px] text-muted">{row.unp ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
