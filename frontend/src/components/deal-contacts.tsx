"use client";

import { Mail, Phone, Plus, Star, UserRound } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  addContact,
  type DealContact,
  type ContactTarget,
  fetchContactsResult,
  setPrimaryContact,
  type FetchContactsResult,
} from "@/lib/api";

type LoadState = "loading" | "ready" | "error";
type LoadMode = "initial" | "refresh";
type RefreshOperation = "add" | "primary" | "retry";

function failureReason(result: Exclude<FetchContactsResult, { status: "ok" }>): string {
  if (result.status === "http_error") return `сервер вернул HTTP ${result.httpStatus}`;
  if (result.status === "network_error") return "ошибка сети";
  return "сервер вернул некорректные данные";
}

function loadFailureMessage(result: Exclude<FetchContactsResult, { status: "ok" }>): string {
  return `Не удалось загрузить контакты: ${failureReason(result)}. Повторите попытку.`;
}

function refreshFailureMessage(
  result: Exclude<FetchContactsResult, { status: "ok" }>,
  operation: RefreshOperation,
): string {
  if (operation === "retry") {
    return `Не удалось обновить список контактов: ${failureReason(result)}. Повторите попытку.`;
  }
  const outcome = operation === "add" ? "Контакт сохранён" : "Основной контакт обновлён";
  return `${outcome}, но список контактов не удалось обновить: ${failureReason(result)}. Повторите попытку.`;
}

export function DealContacts({ dealId: dealProp, clientId }: { dealId: string; clientId?: never } | { clientId: number; dealId?: never }) {
  const dealId = useMemo<ContactTarget>(() => clientId === undefined ? dealProp! : { clientId }, [dealProp, clientId]);
  const requestKey = useRef<string | null>(null);
  const [items, setItems] = useState<DealContact[]>([]);
  const [itemsDealId, setItemsDealId] = useState<ContactTarget | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestVersion = useRef(0);
  const mutationVersion = useRef(0);
  const currentDealId = useRef(dealId);

  useLayoutEffect(() => {
    currentDealId.current = dealId;
  }, [dealId]);

  const loadContacts = useCallback(async (
    targetDealId: ContactTarget,
    mode: LoadMode,
    operation: RefreshOperation = "retry",
  ): Promise<void> => {
    const version = ++requestVersion.current;
    if (mode === "initial") {
      setItems([]);
      setItemsDealId(null);
      setLoadState("loading");
      setLoadError(null);
      setRefreshError(null);
      setStale(false);
      setRefreshing(false);
    } else {
      setRefreshError(null);
      setRefreshing(true);
    }

    let result: FetchContactsResult;
    try {
      result = await fetchContactsResult(targetDealId);
    } catch {
      // Keep a failed refresh separate from the mutation outcome even if a mock
      // or future transport implementation rejects outside the API helper.
      result = { status: "network_error" };
    }
    if (version !== requestVersion.current || currentDealId.current !== targetDealId) return;

    if (result.status === "ok") {
      setItems(result.data);
      setItemsDealId(targetDealId);
      setLoadState("ready");
      setLoadError(null);
      setRefreshError(null);
      setStale(false);
      setRefreshing(false);
      return;
    }

    if (mode === "initial") {
      setItems([]);
      setItemsDealId(targetDealId);
      setLoadState("error");
      setLoadError(loadFailureMessage(result));
      setRefreshError(null);
      setStale(false);
      setRefreshing(false);
    } else {
      setRefreshing(false);
      setRefreshError(refreshFailureMessage(result, operation));
      setStale(true);
    }
  }, []);

  useEffect(() => {
    // A deal change invalidates pending mutations as well as contact loads.
    mutationVersion.current += 1;
    requestKey.current = null;
    // Deal identity is the boundary for this local interaction state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setBusy(false);
    setAdding(false);
    setName("");
    setPhone("");
    setEmail("");
    setError(null);
    void loadContacts(dealId, "initial");

    return () => {
      requestVersion.current += 1;
      mutationVersion.current += 1;
    };
  }, [dealId, loadContacts]);

  const visibleItems = itemsDealId === dealId ? items : [];
  const hasLoadedData = itemsDealId === dealId && loadState === "ready";
  const showEmpty = hasLoadedData && !refreshing && !refreshError && visibleItems.length === 0;
  const showCount = hasLoadedData && (visibleItems.length > 0 || showEmpty);
  const canMutate = hasLoadedData && !refreshing && !refreshError;

  async function onAdd() {
    if (!name.trim() || !canMutate) return;
    const targetDealId = dealId;
    const operation = ++mutationVersion.current;
    setBusy(true);
    setError(null);
    setRefreshError(null);
    setStale(false);
    try {
      const saved = await addContact(targetDealId, {
        request_key: requestKey.current ??= crypto.randomUUID(),
        full_name: name.trim(),
        phone: phone.trim() || undefined,
        email: email.trim() || undefined,
        is_primary: visibleItems.length === 0,
      });
      if (currentDealId.current !== targetDealId || mutationVersion.current !== operation) return;
      if (!saved) {
        setError("Не удалось сохранить контакт. Повторите попытку.");
        return;
      }
      requestKey.current = null;
      setName("");
      setPhone("");
      setEmail("");
      setAdding(false);
      await loadContacts(targetDealId, "refresh", "add");
    } catch {
      if (currentDealId.current === targetDealId && mutationVersion.current === operation) {
        setError("Не удалось сохранить контакт. Повторите попытку.");
      }
    } finally {
      if (currentDealId.current === targetDealId && mutationVersion.current === operation) setBusy(false);
    }
  }

  async function onPrimary(contactId: number) {
    if (!canMutate) return;
    const targetDealId = dealId;
    const operation = ++mutationVersion.current;
    setBusy(true);
    setError(null);
    setRefreshError(null);
    setStale(false);
    try {
      const contact = visibleItems.find((item) => item.id === contactId);
      const primaryClientId = clientId ?? contact?.crm_client_id;
      const saved = primaryClientId === undefined
        ? await setPrimaryContact(contactId) : await setPrimaryContact(contactId, primaryClientId);
      if (currentDealId.current !== targetDealId || mutationVersion.current !== operation) return;
      if (!saved) {
        setError("Не удалось назначить основной контакт. Повторите попытку.");
        return;
      }
      await loadContacts(targetDealId, "refresh", "primary");
    } catch {
      if (currentDealId.current === targetDealId && mutationVersion.current === operation) {
        setError("Не удалось назначить основной контакт. Повторите попытку.");
      }
    } finally {
      if (currentDealId.current === targetDealId && mutationVersion.current === operation) setBusy(false);
    }
  }

  function onRetry() {
    void loadContacts(dealId, loadState === "error" ? "initial" : "refresh");
  }

  return (
    <div className="mt-4 rounded-xl border border-line p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold text-ink">
          <UserRound size={18} className="text-accent-ink" /> Контакты
          {showCount && <span className="text-sm font-medium text-muted">({visibleItems.length})</span>}
        </div>
        <button
          onClick={() => setAdding((v) => !v)}
          disabled={!canMutate || busy}
          className="inline-flex items-center gap-1 text-sm font-medium text-accent-ink hover:text-accent-ink disabled:opacity-60"
        >
          <Plus size={14} /> Добавить
        </button>
      </div>

      {loadState === "loading" && <p role="status" className="mt-3 text-sm text-muted">Загрузка контактов…</p>}

      {loadState === "error" && loadError && (
        <div role="alert" className="mt-3 flex flex-wrap items-center gap-2 text-sm text-red-600">
          <span>{loadError}</span>
          <button onClick={onRetry} className="font-medium underline">Повторить</button>
        </div>
      )}

      {refreshing && <p role="status" className="mt-3 text-sm text-muted">Обновление контактов…</p>}

      {refreshError && (
        <div role="alert" className="mt-3 flex flex-wrap items-center gap-2 text-sm text-red-600">
          <span>{refreshError}</span>
          <button onClick={onRetry} className="font-medium underline">Повторить</button>
        </div>
      )}

      {stale && <p role="status" className="mt-2 text-sm text-amber-700">Показан последний успешно загруженный список; он может быть устаревшим.</p>}

      {hasLoadedData && (visibleItems.length > 0 || showEmpty) && (
        <ul className="mt-3 space-y-2">
          {showEmpty && <li className="text-sm text-muted">Контактов пока нет</li>}
          {visibleItems.map((c) => (
            <li key={c.id} className="flex items-center gap-3 rounded-lg bg-sunken px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm font-medium text-ink">
                  {c.full_name}
                  {c.is_primary && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-600">
                      <Star size={11} className="fill-current" /> основной
                    </span>
                  )}
                </div>
                <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
                  {c.phone && (
                    <span className="inline-flex items-center gap-1">
                      <Phone size={11} /> {c.phone}
                    </span>
                  )}
                  {c.email && (
                    <span className="inline-flex items-center gap-1">
                      <Mail size={11} /> {c.email}
                    </span>
                  )}
                </div>
              </div>
              {!c.is_primary && (
                <button
                  onClick={() => onPrimary(c.id)}
                  disabled={busy || refreshing || Boolean(refreshError)}
                  title="Сделать основным"
                  className="shrink-0 text-faint hover:text-amber-500 disabled:opacity-60"
                >
                  <Star size={16} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <div className="mt-3 space-y-2 rounded-lg border border-line p-3">
          <input
            value={name}
            disabled={busy} onChange={(e) => { setName(e.target.value); requestKey.current = null; }}
            placeholder="ФИО контакта"
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <div className="flex gap-2">
            <input
              value={phone}
              disabled={busy} onChange={(e) => { setPhone(e.target.value); requestKey.current = null; }}
              placeholder="Телефон"
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
            <input
              value={email}
              disabled={busy} onChange={(e) => { setEmail(e.target.value); requestKey.current = null; }}
              placeholder="Email"
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </div>
          <button
            onClick={onAdd}
            disabled={busy || !name.trim() || !canMutate}
            className="w-full rounded-lg bg-accent py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
          >
            Сохранить контакт
          </button>
        </div>
      )}

      {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
    </div>
  );
}
