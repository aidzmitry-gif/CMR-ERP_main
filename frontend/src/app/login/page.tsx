"use client";

import { Box } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { UserInfo } from "@/lib/access";

export default function LoginPage() {
  const router = useRouter();
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/system/users", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { users: [] }))
      .then((d: { users: UserInfo[] }) => {
        setUsers(d.users);
        if (d.users[0]) setUsername(d.users[0].username);
      })
      .catch(() => setError("Не удалось загрузить список сотрудников (backend недоступен)."));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!username) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username }),
      });
      if (!res.ok) {
        setError("Не удалось войти. Попробуйте ещё раз.");
        setBusy(false);
        return;
      }
      router.push("/crm/deals");
      router.refresh();
    } catch {
      setError("Сеть недоступна.");
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-2xl bg-white p-7 shadow-card"
      >
        <div className="mb-6 flex items-center gap-2">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand text-white">
            <Box size={22} />
          </span>
          <div>
            <div className="text-lg font-bold text-ink">AI-OS · ERP</div>
            <div className="text-xs text-muted">Вход (dev)</div>
          </div>
        </div>

        <label className="mb-1 block text-sm font-medium text-slate-700" htmlFor="user">
          Сотрудник
        </label>
        <select
          id="user"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="mb-4 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-ink"
        >
          {users.map((u) => (
            <option key={u.username} value={u.username}>
              {u.full_name} — {u.role_title}
            </option>
          ))}
        </select>

        {error && <div className="mb-3 text-sm text-red-600">{error}</div>}

        <button
          type="submit"
          disabled={busy || !username}
          className="w-full rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Вход…" : "Войти"}
        </button>

        <p className="mt-4 text-center text-xs text-muted">
          Dev-вход без пароля. Реальная авторизация — позже (Keycloak).
        </p>
      </form>
    </div>
  );
}
