import { validCommand, validOutcome, type EditCommand, type EditOutcome, type Identity } from "./procurement-machine";
export type Scope = Identity & { order_id: number };
export type Attempt = { version: 1; org: number; principal: string; order_id: number; revision: number; body: string; mode: "execute" | "reconcile"; state: "pending" | "settled"; result?: EditOutcome };
export interface AtomicStore { change(scope: string, update: (current: Attempt | null) => Attempt | null): Promise<Attempt | null> }
const scopeKey = (s: Scope) => JSON.stringify([s.organization_id, s.principal, s.order_id]);
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
function check(a: Attempt, s: Scope) {
  if (a.version !== 1 || a.org !== s.organization_id || a.principal !== s.principal || a.order_id !== s.order_id || !Number.isSafeInteger(a.revision) || a.revision < 1 || !["pending", "settled"].includes(a.state) || !["execute", "reconcile"].includes(a.mode)) throw new Error("Журнал команд повреждён");
  const command = JSON.parse(a.body);
  if (!validCommand(command) || command.order_id !== s.order_id || JSON.stringify(command) !== a.body || (a.state === "pending" && a.result !== undefined) || (a.state === "settled" && !a.result)) throw new Error("Журнал команд повреждён");
  return command as EditCommand;
}
// Both stores are updated in one native readwrite transaction. No async callback
// is allowed inside it; HTTP and hashing happen after transaction completion.
export const indexedStore: AtomicStore = {
  async change(key, update) {
    return new Promise<Attempt | null>((resolve, reject) => {
      const open = indexedDB.open("procurement-editor-commands", 1);
      open.onupgradeneeded = () => { open.result.createObjectStore("active"); open.result.createObjectStore("attempts"); };
      open.onerror = () => reject(open.error ?? new Error("Хранилище недоступно"));
      let blocked = false;
      open.onblocked = () => { blocked = true; reject(new Error("Обновление хранилища заблокировано другой вкладкой")); };
      open.onsuccess = () => {
        const db = open.result;
        if (blocked) { db.close(); return; }
        let tx: IDBTransaction;
        try { tx = db.transaction(["active", "attempts"], "readwrite"); }
        catch (e) { db.close(); reject(e); return; }
        let result: Attempt | null = null; let failure: unknown;
        tx.oncomplete = () => { db.close(); resolve(result); };
        tx.onabort = () => { db.close(); reject(failure ?? tx.error ?? new Error("Запись журнала отменена")); };
        tx.onerror = () => { /* onabort owns the rejection */ };
        const active = tx.objectStore("active"); const attempts = tx.objectStore("attempts");
        function apply(current: Attempt | null) {
          try {
            result = update(current);
            if (result) {
              const id = JSON.stringify([key, JSON.parse(result.body).request_key]);
              attempts.put(result, id); active.put(id, key);
            } else if (current) throw new Error("Удаление попытки не разрешено");
          } catch (e) { failure = e; tx.abort(); }
        }
        const pointer = active.get(key);
        pointer.onsuccess = () => {
          if (pointer.result === undefined) { apply(null); return; }
          if (typeof pointer.result !== "string") { failure = new Error("Повреждена ссылка журнала"); tx.abort(); return; }
          const stored = attempts.get(pointer.result);
          stored.onsuccess = () => { if (stored.result === undefined) { failure = new Error("Повреждена ссылка журнала"); tx.abort(); } else apply(stored.result); };
        };
      };
    });
  },
};
export function createJournal(store: AtomicStore) {
  async function load(s: Scope): Promise<Attempt | null> {
    const a = await store.change(scopeKey(s), current => current);
    if (a) { const command = check(a, s); if (a.state === "settled" && !(await validOutcome(a.result, s, command))) throw new Error("Сохранённый результат повреждён"); }
    return a;
  }
  return {
    load,
    async claim(s: Scope, expected: Attempt | null, action: EditCommand["action"], payload: Record<string, unknown>) {
      let created = false;
      const attempt = await store.change(scopeKey(s), current => {
        if (current) check(current, s);
        if (current?.state === "pending") return current;
        if (!same(current, expected)) throw new Error("Журнал изменился в другой вкладке. Обновите заказ.");
        const command: EditCommand = { version: 1, request_key: crypto.randomUUID(), order_id: s.order_id, action, payload };
        if (!validCommand(command)) throw new Error("Некорректная команда");
        created = true;
        return { version: 1, org: s.organization_id, principal: s.principal, order_id: s.order_id, revision: (current?.revision ?? 0) + 1, body: JSON.stringify(command), mode: "execute", state: "pending" };
      });
      return { attempt: attempt!, created };
    },
    async reconcile(s: Scope, expected: Attempt) {
      const attempt = await store.change(scopeKey(s), current => {
        if (!current) throw new Error("Попытка не найдена"); check(current, s);
        if (!same(current, expected) || current.state !== "pending") throw new Error("Журнал изменился. Обновите попытку.");
        return current.mode === "reconcile" ? current : { ...current, mode: "reconcile", revision: current.revision + 1 };
      }); return attempt!;
    },
    async settle(s: Scope, expected: Attempt, result: EditOutcome) {
      const command = check(expected, s);
      if (!(await validOutcome(result, s, command))) throw new Error("Ответ не подтверждает команду");
      const attempt = await store.change(scopeKey(s), current => {
        if (!current) throw new Error("Попытка не найдена"); check(current, s);
        if (current.body === expected.body && current.state === "settled" && same(current.result, result)) return current;
        if (current.body !== expected.body || current.state !== "pending") throw new Error("Попытка изменилась. Ответ не применён.");
        // A concurrent switch to reconcile can still accept the exact same
        // terminal server receipt. The server serializes execute/reconcile.
        return { ...current, state: "settled", result, revision: current.revision + 1 };
      }); return attempt!;
    },
  };
}
export const editorJournal = createJournal(indexedStore);
