"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

const empty = {
  provider: "", account_code: "", external_id: "", operation_date: "", amount: "",
  counterparty_name: "", counterparty_identifier: "", purpose: "", source_reference: "", evidence: "",
};

export function AccountingBankStatementSource({ org, disabled, onImported }: {
  org: string; disabled: boolean; onImported: () => Promise<void>;
}) {
  const [fields, setFields] = useState(empty);
  const [direction, setDirection] = useState("receipt");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || disabled) return;
    setBusy(true); setError(""); setNotice("");
    const { evidence, ...source } = fields;
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/bank-statement/sources`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ evidence, line: { ...source, direction, currency: "BYN", source_kind: "file",
          counterparty_name: source.counterparty_name || null,
          counterparty_identifier: source.counterparty_identifier || null } }),
      });
      const result = await response.json();
      if (!alive.current) return;
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Проверьте реквизиты строки выписки.");
      setNotice("Строка сохранена. Выберите её в очереди, чтобы проверить и подтвердить проводки.");
      await onImported();
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : "Не удалось сохранить строку выписки.");
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  const controls: { key: keyof typeof empty; label: string; type?: string; optional?: boolean; max: number }[] = [
    { key: "provider", label: "Банк (одинаковое обозначение во всех выписках)", max: 100 },
    { key: "account_code", label: "Наш банковский счёт", max: 64 },
    { key: "external_id", label: "Идентификатор операции в банке", max: 200 },
    { key: "operation_date", label: "Дата операции", type: "date", max: 10 },
    { key: "amount", label: "Сумма BYN", max: 15 },
    { key: "counterparty_name", label: "Контрагент", optional: true, max: 255 },
    { key: "counterparty_identifier", label: "УНП контрагента", optional: true, max: 32 },
    { key: "purpose", label: "Назначение платежа", optional: true, max: 512 },
    { key: "source_reference", label: "Название файла или номер выписки", max: 500 },
    { key: "evidence", label: "Основание принадлежности счёта выбранному юрлицу", max: 1000 },
  ];
  return <details className="rounded-xl border border-border p-3">
    <summary className="cursor-pointer font-semibold">Добавить строку из выписки</summary>
    <p className="my-2 text-sm text-muted">Главный бухгалтер указывает реквизиты из выписки выбранного юрлица. Поддерживается BYN. Сохранение строки ещё не проводит её в учёте.</p>
    <form onSubmit={(event) => void submit(event)} className="space-y-3">
      <fieldset disabled={busy || disabled} className="grid gap-3 md:grid-cols-2">
        <label>Направление<Select aria-label="Направление строки выписки" value={direction} onChange={(event) => setDirection(event.target.value)}><option value="receipt">Поступление</option><option value="payment">Списание</option></Select></label>
        {controls.map(({ key, label, type, optional, max }) => <label key={key}>{label}
          <Input aria-label={label} type={type || "text"} required={!optional} maxLength={max}
            inputMode={key === "amount" ? "decimal" : undefined} value={fields[key]}
            onChange={(event) => setFields((current) => ({ ...current, [key]: event.target.value }))} />
        </label>)}
      </fieldset>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {notice && <p role="status" className="text-money">{notice}</p>}
      <Button type="submit" disabled={busy || disabled || !org}>{busy ? "Сохранение…" : "Сохранить строку выписки"}</Button>
    </form>
  </details>;
}
