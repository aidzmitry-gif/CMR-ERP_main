"use client";

import { Mail, Phone, Plus, Star, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { addContact, type DealContact, fetchContacts, setPrimaryContact } from "@/lib/api";

export function DealContacts({ dealId }: { dealId: string }) {
  const [items, setItems] = useState<DealContact[]>([]);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setItems(await fetchContacts(dealId));
  }

  useEffect(() => {
    void fetchContacts(dealId).then(setItems);
  }, [dealId]);

  async function onAdd() {
    if (!name.trim()) return;
    setBusy(true);
    await addContact(dealId, {
      full_name: name.trim(),
      phone: phone.trim() || undefined,
      email: email.trim() || undefined,
      is_primary: items.length === 0,
    });
    setName("");
    setPhone("");
    setEmail("");
    setAdding(false);
    await refresh();
    setBusy(false);
  }

  async function onPrimary(contactId: number) {
    setBusy(true);
    await setPrimaryContact(contactId);
    await refresh();
    setBusy(false);
  }

  return (
    <div className="mt-4 rounded-xl border border-line p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold text-ink">
          <UserRound size={18} className="text-accent-ink" /> Контакты
          <span className="text-sm font-medium text-muted">({items.length})</span>
        </div>
        <button
          onClick={() => setAdding((v) => !v)}
          className="inline-flex items-center gap-1 text-sm font-medium text-accent-ink hover:text-accent-ink"
        >
          <Plus size={14} /> Добавить
        </button>
      </div>

      <ul className="mt-3 space-y-2">
        {items.length === 0 && <li className="text-sm text-muted">Контактов пока нет</li>}
        {items.map((c) => (
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
                disabled={busy}
                title="Сделать основным"
                className="shrink-0 text-faint hover:text-amber-500 disabled:opacity-60"
              >
                <Star size={16} />
              </button>
            )}
          </li>
        ))}
      </ul>

      {adding && (
        <div className="mt-3 space-y-2 rounded-lg border border-line p-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="ФИО контакта"
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <div className="flex gap-2">
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="Телефон"
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </div>
          <button
            onClick={onAdd}
            disabled={busy || !name.trim()}
            className="w-full rounded-lg bg-accent py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
          >
            Сохранить контакт
          </button>
        </div>
      )}
    </div>
  );
}
