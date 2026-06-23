"use client";

import {
  Archive,
  CheckCircle2,
  ClipboardList,
  FileBarChart,
  FileText,
  Folder,
  History,
  Lock,
  RotateCcw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Trash2,
  TriangleAlert,
  User,
} from "lucide-react";
import { useMemo, useState } from "react";
import { formatByn } from "@/lib/format";

// demo-данные (бэкенда по экрану пока нет). Валюта — BYN.
// Архив документов — модуль ВНЕ CRM: безвозвратное удаление помеченных в сделках
// документов/версий. Доступ — только у архивариуса (роль doc_admin). Всё логируется.

type IconCmp = React.ComponentType<{ size?: number; className?: string }>;

type Verdict = "safe" | "risk" | "none";

type TrashDoc = {
  id: string;
  n: string;
  kind: string;
  ver: number;
  deal: string;
  client: string;
  by: string;
  dept: string;
  at: string; // дд.мм.гггг чч:мм
  amount: number;
  reason: string;
  // ИИ-вердикт задан в данных (без вычислений в рендере, чтобы не ломать гидрацию SSR≠client)
  ai: Verdict;
  aiWhy: string;
};

type AuditEntry = {
  id: string;
  at: string; // дд.мм.гггг чч:мм
  who: string;
  action: "purge" | "restore" | "purge-group";
  target: string;
  reason: string;
};

const DEPT_ICON: Record<string, IconCmp> = {
  "Отдел продаж · Новые": Folder,
  "Отдел продаж · Постоянные": RotateCcw,
  "Тендерный отдел": FileBarChart,
  "Юридический отдел": Scale,
};

const VERDICT_CLS: Record<Verdict, string> = {
  safe: "bg-emerald-50 text-emerald-600",
  risk: "bg-red-50 text-red-600",
  none: "bg-sunken text-faint",
};

const VERDICT_LABEL: Record<Verdict, string> = {
  safe: "Можно удалять",
  risk: "Разобраться",
  none: "Не проверено",
};

// помеченные на удаление документы/версии (приходят из карточек сделок)
const INITIAL_TRASH: TrashDoc[] = [
  {
    id: "t-1",
    n: "Счёт СЧ-0461 (черновик)",
    kind: "Счёт на оплату",
    ver: 1,
    deal: "CRM-1024 · Автопарк №7",
    client: "Автопарк №7",
    by: "Сидоров К.",
    dept: "Отдел продаж · Новые",
    at: "14.06.2026 11:20",
    amount: 12_400,
    reason: "ошибка в позициях, выставлен новый",
    ai: "safe",
    aiWhy: "рутинная замена черновика/ошибки",
  },
  {
    id: "t-2",
    n: "КП-0288 — годовая поставка",
    kind: "Коммерческое предложение",
    ver: 1,
    deal: "CRM-1024 · Автопарк №7",
    client: "Автопарк №7",
    by: "Петрова А.",
    dept: "Отдел продаж · Новые",
    at: "13.06.2026 16:05",
    amount: 45_000,
    reason: "устаревшие цены",
    ai: "safe",
    aiWhy: "рутинная замена черновика/ошибки",
  },
  {
    id: "t-3",
    n: "Договор ДГ-0118 — годовая поставка",
    kind: "Договор · версия",
    ver: 1,
    deal: "CRM-1029 · ОАО «Белтранс»",
    client: "Белтранс",
    by: "Сидоров К.",
    dept: "Отдел продаж · Новые",
    at: "12.06.2026 09:40",
    amount: 86_000,
    reason: "черновик до правок юриста",
    ai: "safe",
    aiWhy: "рутинная замена черновика/ошибки",
  },
  {
    id: "t-4",
    n: "Счёт СЧ-0455 — поставка Q2",
    kind: "Счёт на оплату",
    ver: 2,
    deal: "CRM-1031 · СТО «Вираж»",
    client: "СТО Вираж",
    by: "Иванов И.",
    dept: "Отдел продаж · Постоянные",
    at: "11.06.2026 14:10",
    amount: 31_000,
    reason: "счёт оплачен, но клиент просит переоформить — заменён",
    ai: "risk",
    aiWhy: "документ мог иметь юридическую/финансовую силу",
  },
  {
    id: "t-5",
    n: "Договор ДГ-0120 — тендер РУП",
    kind: "Договор · версия",
    ver: 1,
    deal: "CRM-1040 · РУП «Белэнерго»",
    client: "Белэнерго",
    by: "Морозов Д.",
    dept: "Тендерный отдел",
    at: "10.06.2026 10:30",
    amount: 240_000,
    reason: "подписан, но переподписан с новой редакцией приложения",
    ai: "risk",
    aiWhy: "документ мог иметь юридическую/финансовую силу",
  },
  {
    id: "t-6",
    n: "Акт сверки АС-0044",
    kind: "Акт сверки · версия",
    ver: 1,
    deal: "CRM-1015 · ООО «Логист»",
    client: "Логист",
    by: "Юрист Юрьев",
    dept: "Юридический отдел",
    at: "09.06.2026 15:55",
    amount: 19_800,
    reason: "дубликат, повтор за тот же период",
    ai: "safe",
    aiWhy: "рутинная замена черновика/ошибки",
  },
];

// журнал аудита (необратимые действия пишутся сюда; кто/что/когда/основание)
const INITIAL_AUDIT: AuditEntry[] = [
  {
    id: "a-1",
    at: "13.06.2026 18:42",
    who: "Архивариус · Кузнецова Л.",
    action: "purge",
    target: "Счёт СЧ-0440 (черновик)",
    reason: "опечатка в реквизитах, выставлен новый",
  },
  {
    id: "a-2",
    at: "13.06.2026 12:08",
    who: "Архивариус · Кузнецова Л.",
    action: "restore",
    target: "КП-0270 — поставка АКБ",
    reason: "ошибочная пометка, документ актуален",
  },
  {
    id: "a-3",
    at: "11.06.2026 09:15",
    who: "Архивариус · Кузнецова Л.",
    action: "purge-group",
    target: "Тендерный отдел · 3 док./версий",
    reason: "устаревшие черновики до согласования",
  },
];

const PURGE_LABEL: Record<AuditEntry["action"], string> = {
  purge: "удалён безвозвратно",
  restore: "восстановлен",
  "purge-group": "удалено группой",
};

const PURGE_ICON: Record<AuditEntry["action"], IconCmp> = {
  purge: Trash2,
  restore: RotateCcw,
  "purge-group": Trash2,
};

const PURGE_TONE: Record<AuditEntry["action"], string> = {
  purge: "text-red-600",
  restore: "text-emerald-600",
  "purge-group": "text-red-600",
};

export function DocsArchive() {
  const [items, setItems] = useState<TrashDoc[]>(INITIAL_TRASH);
  const [audit, setAudit] = useState<AuditEntry[]>(INITIAL_AUDIT);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [aiDone, setAiDone] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  function notify(msg: string) {
    setToast(msg);
  }

  // ── скорборд ────────────────────────────────────────────────────────────
  const stats = useMemo(() => {
    const sum = items.reduce((s, d) => s + d.amount, 0);
    const safe = items.filter((d) => d.ai === "safe").length;
    const risk = items.filter((d) => d.ai === "risk").length;
    return { count: items.length, sum, safe, risk };
  }, [items]);

  // ── группировка по отделам ──────────────────────────────────────────────
  const groups = useMemo(() => {
    const buckets = new Map<string, TrashDoc[]>();
    for (const d of items) {
      const arr = buckets.get(d.dept) ?? [];
      arr.push(d);
      buckets.set(d.dept, arr);
    }
    return [...buckets.keys()].sort().map((dept) => {
      const list = buckets.get(dept) ?? [];
      return {
        dept,
        icon: DEPT_ICON[dept] ?? Folder,
        items: list,
        sum: list.reduce((s, d) => s + d.amount, 0),
        selCount: list.filter((d) => selected.has(d.id)).length,
        allSel: list.length > 0 && list.every((d) => selected.has(d.id)),
      };
    });
  }, [items, selected]);

  // ── ИИ-проверка причин (демо: вердикты заданы в данных) ──────────────────
  function runAi() {
    setAiDone(true);
    notify(
      `ИИ проверил основания: ${stats.safe} безопасных, ${stats.risk} на разбор`,
    );
  }

  function selectSafe(on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const d of items) {
        if (d.ai === "safe") {
          if (on) next.add(d.id);
          else next.delete(d.id);
        }
      }
      return next;
    });
  }

  const allSafeSelected = useMemo(() => {
    const safeIds = items.filter((d) => d.ai === "safe");
    return safeIds.length > 0 && safeIds.every((d) => selected.has(d.id));
  }, [items, selected]);

  // ── выбор ────────────────────────────────────────────────────────────────
  function toggleOne(id: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function toggleDept(dept: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const d of items) {
        if (d.dept === dept) {
          if (on) next.add(d.id);
          else next.delete(d.id);
        }
      }
      return next;
    });
  }

  function pushAudit(entry: Omit<AuditEntry, "id">) {
    setAudit((prev) => [
      { ...entry, id: `a-${prev.length + INITIAL_AUDIT.length + 1}` },
      ...prev,
    ]);
  }

  // ── восстановление (снять пометку, вернуть в сделку) ──────────────────────
  function restore(doc: TrashDoc) {
    setItems((list) => list.filter((d) => d.id !== doc.id));
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(doc.id);
      return next;
    });
    pushAudit({
      at: "23.06.2026 09:30",
      who: "Архивариус · Кузнецова Л.",
      action: "restore",
      target: doc.n,
      reason: "пометка снята, документ вернулся в сделку",
    });
    notify(`Восстановлено: ${doc.n} — пометка снята, документ вернулся в сделку`);
  }

  // ── безвозвратное удаление одного ─────────────────────────────────────────
  function purge(doc: TrashDoc) {
    setItems((list) => list.filter((d) => d.id !== doc.id));
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(doc.id);
      return next;
    });
    pushAudit({
      at: "23.06.2026 09:30",
      who: "Архивариус · Кузнецова Л.",
      action: "purge",
      target: doc.n,
      reason: doc.reason,
    });
    notify(`Удалено безвозвратно: ${doc.n} · записано в журнал аудита`);
  }

  // ── безвозвратное удаление группой по отделу ──────────────────────────────
  function purgeDept(dept: string) {
    const toPurge = items.filter((d) => d.dept === dept && selected.has(d.id));
    if (toPurge.length === 0) {
      notify("Не отмечено ни одного документа в отделе");
      return;
    }
    const ids = new Set(toPurge.map((d) => d.id));
    setItems((list) => list.filter((d) => !ids.has(d.id)));
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) next.delete(id);
      return next;
    });
    pushAudit({
      at: "23.06.2026 09:30",
      who: "Архивариус · Кузнецова Л.",
      action: "purge-group",
      target: `${dept} · ${toPurge.length} док./версий`,
      reason: "групповое удаление отмеченных",
    });
    notify(
      `Удалено группой: ${toPurge.length} док. («${dept}») · в журнал аудита`,
    );
  }

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-[1220px] space-y-4">
        {/* Заголовок */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-bold text-ink">
              <Archive size={20} className="text-accent" /> Архив документов
            </h1>
            <p className="mt-1 max-w-3xl text-sm text-muted">
              Сюда попадают документы и версии,{" "}
              <b className="font-semibold text-ink">помеченные на удаление</b> в карточках
              сделок. В самой CRM удалить документ нельзя — только пометить. Безвозвратное
              удаление выполняется здесь, сгруппировано по отделам: можно отметить отдел и
              удалить группой.
            </p>
          </div>
        </div>

        {/* Гейт доступа — роль архивариуса */}
        <div className="flex gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4">
          <ShieldAlert size={22} className="mt-0.5 flex-shrink-0 text-amber-600" />
          <div className="space-y-2 text-[13px] leading-relaxed text-amber-700">
            <div>
              Доступ к безвозвратному удалению —{" "}
              <b className="font-semibold">только у ответственного за архив</b>. Этот модуль
              не входит в CRM: менеджеры и РОП сюда не имеют доступа (разделение полномочий,
              защита от потери документов и подмены истории).
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[12px]">
              <span>Сейчас вошёл:</span>
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-surface px-2.5 py-0.5 font-semibold">
                <User size={12} /> Архивариус · Кузнецова Л.
              </span>
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-surface px-2.5 py-0.5 font-semibold">
                <ShieldCheck size={12} /> роль: doc_admin
              </span>
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-surface px-2.5 py-0.5 font-semibold">
                <Lock size={12} /> действия логируются
              </span>
            </div>
          </div>
        </div>

        {/* Скорборд / KPI */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
            <div className="flex items-center gap-1.5 text-xl font-bold tabular-nums text-ink">
              <Trash2 size={16} className="text-muted" /> {stats.count}
            </div>
            <div className="mt-1 text-[11.5px] text-muted">помечено на удаление</div>
          </div>
          <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
            <div className="text-xl font-bold tabular-nums text-money">
              {formatByn(stats.sum)}
            </div>
            <div className="mt-1 text-[11.5px] text-muted">сумма помеченных</div>
          </div>
          <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
            <div className="flex items-center gap-1.5 text-xl font-bold tabular-nums text-emerald-600">
              <CheckCircle2 size={16} /> {aiDone ? stats.safe : "—"}
            </div>
            <div className="mt-1 text-[11.5px] text-muted">
              {aiDone ? "ИИ: можно удалять" : "ИИ ещё не проверял"}
            </div>
          </div>
          <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
            <div className="flex items-center gap-1.5 text-xl font-bold tabular-nums text-red-600">
              <TriangleAlert size={16} /> {aiDone ? stats.risk : "—"}
            </div>
            <div className="mt-1 text-[11.5px] text-muted">
              {aiDone ? "ИИ: требуют разбора" : "ИИ ещё не проверял"}
            </div>
          </div>
        </div>

        {/* ИИ-проверка причин удаления */}
        <div className="flex flex-wrap items-center gap-3 rounded-2xl border-l-4 border-violet-400 border-y border-r border-y-line border-r-line bg-surface p-4 shadow-card">
          <Sparkles size={18} className="flex-shrink-0 text-violet-500" />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-ink">
              ИИ-проверка причин удаления
            </div>
            <div className="mt-0.5 text-[12.5px] text-muted">
              {aiDone ? (
                <>
                  ИИ разобрал {stats.count} основ.:{" "}
                  <b className="text-emerald-600">{stats.safe}</b> безопасных (реком.
                  удалять) · <b className="text-red-600">{stats.risk}</b> требуют разбора
                  (не удалять без проверки).
                </>
              ) : (
                "Нажмите «Проверить» — ИИ разберёт основания и отметит безопасные / требующие разбора."
              )}
            </div>
          </div>

          {aiDone && stats.safe > 0 && (
            <label className="flex cursor-pointer select-none items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[12.5px] font-semibold text-emerald-600">
              <input
                type="checkbox"
                checked={allSafeSelected}
                onChange={(e) => selectSafe(e.target.checked)}
                className="accent-emerald-500"
              />
              отметить всё, что ИИ разрешил удалять
            </label>
          )}

          <button
            type="button"
            onClick={runAi}
            disabled={aiDone}
            className={
              aiDone
                ? "ml-auto inline-flex items-center gap-1.5 rounded-xl bg-sunken px-4 py-2 text-[13px] font-semibold text-faint"
                : "ml-auto inline-flex items-center gap-1.5 rounded-xl bg-violet-500 px-4 py-2 text-[13px] font-semibold text-white hover:bg-violet-600"
            }
          >
            {aiDone ? (
              <>
                <CheckCircle2 size={14} /> Проверено
              </>
            ) : (
              <>
                <Sparkles size={14} /> Проверить причины
              </>
            )}
          </button>
        </div>

        {/* Список помеченных — по отделам */}
        {groups.length === 0 ? (
          <div className="flex items-center justify-center gap-2 rounded-2xl border border-line bg-surface p-10 text-center text-sm text-faint shadow-card">
            <CheckCircle2 size={16} className="text-emerald-600" /> Нет документов,
            помеченных на удаление
          </div>
        ) : (
          groups.map((g) => {
            const GroupIcon = g.icon;
            return (
              <div
                key={g.dept}
                className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card"
              >
                {/* Шапка отдела */}
                <div className="flex flex-wrap items-center gap-3 border-b border-line bg-sunken px-4 py-3">
                  <label className="flex cursor-pointer select-none items-center gap-1.5 text-[12.5px] text-muted">
                    <input
                      type="checkbox"
                      checked={g.allSel}
                      onChange={(e) => toggleDept(g.dept, e.target.checked)}
                      className="accent-red-500"
                    />
                    отметить отдел
                  </label>
                  <span className="flex items-center gap-2 text-sm font-semibold text-ink">
                    <GroupIcon size={15} className="text-muted" /> {g.dept}
                  </span>
                  <span className="rounded-full bg-surface px-2.5 py-0.5 text-[11px] font-semibold text-muted">
                    {g.items.length} док./версий
                  </span>
                  <span className="hidden text-xs tabular-nums text-muted sm:inline">
                    {formatByn(g.sum)}
                  </span>
                  <button
                    type="button"
                    onClick={() => purgeDept(g.dept)}
                    disabled={g.selCount === 0}
                    className={
                      g.selCount > 0
                        ? "ml-auto inline-flex items-center gap-1.5 rounded-xl bg-red-500 px-3 py-1.5 text-[12.5px] font-semibold text-white hover:bg-red-600"
                        : "ml-auto inline-flex items-center gap-1.5 rounded-xl bg-sunken px-3 py-1.5 text-[12.5px] font-semibold text-faint"
                    }
                  >
                    <Trash2 size={13} />
                    {g.selCount > 0
                      ? `Удалить отмеченные (${g.selCount})`
                      : "Удалить отмеченные"}
                  </button>
                </div>

                {/* Строки */}
                {g.items.map((d) => (
                  <TrashRow
                    key={d.id}
                    doc={d}
                    selected={selected.has(d.id)}
                    aiDone={aiDone}
                    onToggle={(on) => toggleOne(d.id, on)}
                    onRestore={() => restore(d)}
                    onPurge={() => purge(d)}
                  />
                ))}
              </div>
            );
          })
        )}

        {/* Журнал аудита */}
        <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
          <div className="flex items-center gap-2 border-b border-line bg-sunken px-4 py-3">
            <History size={15} className="text-muted" />
            <span className="text-sm font-semibold text-ink">Журнал аудита</span>
            <span className="rounded-full bg-surface px-2.5 py-0.5 text-[11px] font-semibold text-muted">
              {audit.length}
            </span>
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-faint">
              <Lock size={11} /> необратимо · кто / что / когда / основание
            </span>
          </div>
          <ul className="divide-y divide-line">
            {audit.map((e) => {
              const Icon = PURGE_ICON[e.action];
              return (
                <li key={e.id} className="flex items-start gap-3 px-4 py-3">
                  <Icon
                    size={15}
                    className={`mt-0.5 flex-shrink-0 ${PURGE_TONE[e.action]}`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] text-ink">
                      <b className="font-semibold">{e.target}</b>{" "}
                      <span className={`font-semibold ${PURGE_TONE[e.action]}`}>
                        {PURGE_LABEL[e.action]}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[11.5px] text-muted">
                      {e.who} · {e.at} · основание: {e.reason}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>

        {/* Сноска */}
        <div className="flex gap-2 rounded-xl border border-line bg-sunken p-3 text-[11.5px] leading-relaxed text-muted">
          <ClipboardList size={15} className="mt-0.5 flex-shrink-0 text-faint" />
          <span>
            Каждое безвозвратное удаление пишется в журнал аудита (кто, что, когда,
            основание) и необратимо. Восстановление снимает пометку и возвращает документ в
            карточку сделки.{" "}
            <b className="font-semibold text-ink">ИИ-проверка — подсказка, а не разрешение:</b>{" "}
            окончательное решение и ответственность — за архивариусом.
          </span>
        </div>
      </div>

      {toast && (
        <div className="fixed bottom-7 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-ink px-4 py-2.5 text-[13px] font-medium text-canvas shadow-pop">
          {toast}
        </div>
      )}
    </main>
  );
}

function TrashRow({
  doc,
  selected,
  aiDone,
  onToggle,
  onRestore,
  onPurge,
}: {
  doc: TrashDoc;
  selected: boolean;
  aiDone: boolean;
  onToggle: (on: boolean) => void;
  onRestore: () => void;
  onPurge: () => void;
}) {
  const verdict: Verdict = aiDone ? doc.ai : "none";

  return (
    <div
      className={`grid grid-cols-[20px_1fr_auto_auto_auto] items-center gap-3.5 border-b border-line px-4 py-3 last:border-0 ${
        selected ? "bg-red-50/50" : ""
      }`}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={(e) => onToggle(e.target.checked)}
        className="accent-red-500"
      />

      <div className="min-w-0">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
          <span className="truncate">{doc.n}</span>
          <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-bold text-accent-ink">
            v{doc.ver}
          </span>
        </div>
        <div className="mt-0.5 truncate text-[11.5px] text-muted">
          <span className="font-semibold text-accent-ink">{doc.deal}</span> · пометил{" "}
          {doc.by} · {doc.at} ·{" "}
          <b className="tabular-nums text-ink">{formatByn(doc.amount)}</b>
          <br />
          основание: {doc.reason}
        </div>
      </div>

      <span className="hidden whitespace-nowrap rounded-md bg-sunken px-2 py-1 text-[11px] font-semibold text-muted md:inline-flex md:items-center md:gap-1.5">
        <FileText size={12} /> {doc.kind}
      </span>

      <span
        className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-semibold ${VERDICT_CLS[verdict]}`}
        title={verdict !== "none" ? doc.aiWhy : "ИИ ещё не проверял основания"}
      >
        {verdict === "safe" ? (
          <CheckCircle2 size={12} />
        ) : verdict === "risk" ? (
          <TriangleAlert size={12} />
        ) : null}
        {VERDICT_LABEL[verdict]}
      </span>

      <div className="flex gap-1.5">
        <button
          type="button"
          onClick={onRestore}
          title="Снять пометку и вернуть в сделку"
          className="inline-flex items-center gap-1 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] font-semibold text-muted hover:border-emerald-300 hover:text-emerald-600"
        >
          <RotateCcw size={13} /> Восстановить
        </button>
        <button
          type="button"
          onClick={onPurge}
          title="Удалить безвозвратно (в журнал аудита)"
          className="inline-flex items-center gap-1 rounded-lg bg-red-500 px-2.5 py-1.5 text-[12px] font-semibold text-white hover:bg-red-600"
        >
          <Trash2 size={13} /> Удалить
        </button>
      </div>
    </div>
  );
}
