import Link from "next/link";
import { ArrowLeft, Mail, Phone, Star, User } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { fetchLeads } from "@/lib/api";
import { currentRole } from "@/lib/role-server";

/**
 * Полная страница лида (открывается двойным кликом по карточке на канбане).
 * MVP-структура по аналогии с /crm/deals/[id]: AppShell + 2-колонная сетка
 * + блоки (контакт, потребность, сообщение, AI, документы заявки stub,
 * задачи stub, переписка stub). Когда подоспеют lead-detail-API — оживляем
 * каждый stub отдельным коммитом.
 */
export default async function LeadDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const role = await currentRole();
  // Простой MVP: тащим все лиды и фильтруем по id (для быстрого старта;
  // когда появится /api/sales/leads/{id} — заменим на точечный fetch).
  const leads = await fetchLeads(role);
  const lead = leads.find((l) => String(l.id) === id) ?? null;

  return (
    <AppShell crumbs={["CRM", "Лиды", `ЛИД-${id}`]}>
      <div className="flex-1 overflow-y-auto bg-canvas text-ink">
        <div className="mx-auto max-w-[1280px] px-[22px] pb-10 pt-[18px]">
          <Link
            href="/crm/leads"
            className="mb-3 inline-flex items-center gap-1 text-[12.5px] font-semibold text-muted hover:text-ink"
          >
            <ArrowLeft size={14} /> К лидам
          </Link>

          {!lead ? (
            <Card className="px-[18px] py-[14px]">
              <div className="text-[13px] text-muted">
                Лид с id={id} не найден. Возможно, удалён или ещё не приехал с бэкенда.{" "}
                <Link className="font-semibold text-accent-ink" href="/crm/leads">
                  Открыть инбокс
                </Link>
                .
              </div>
            </Card>
          ) : (
            <>
              {/* ── ШАПКА ── */}
              <Card className="mb-3.5 px-[18px] py-[13px]">
                <div className="text-[12.5px] text-muted">
                  № ЛИД-{lead.id} · {lead.source}
                </div>
                <h1 className="mt-px text-[19px] font-extrabold leading-tight text-ink">
                  {lead.company || lead.name || "Лид без имени"}
                </h1>
                {lead.region && (
                  <div className="mt-0.5 text-[12.5px] text-muted">{lead.region}</div>
                )}
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
                  <span className="rounded-md bg-sunken px-1.5 py-0.5 font-semibold text-muted">
                    статус · {lead.status}
                  </span>
                  {lead.qualification && (
                    <span
                      className={`rounded-md px-1.5 py-0.5 font-semibold ${
                        lead.qualification === "target"
                          ? "bg-money-soft text-money"
                          : "bg-sunken text-muted"
                      }`}
                    >
                      {lead.score} · {lead.qualification === "target" ? "целевой" : "нецелевой"}
                    </span>
                  )}
                </div>
              </Card>

              {/* ── СЕТКА 1.5fr / 1fr ── */}
              <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1.5fr_1fr]">
                {/* LEFT — содержимое заявки */}
                <div className="min-w-0 space-y-4">
                  <Card>
                    <CardHeader>
                      <span aria-hidden>📝</span>
                      <span>Заявка клиента</span>
                    </CardHeader>
                    <CardBody className="space-y-3">
                      {lead.product && (
                        <div>
                          <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                            <Star size={11} className="mr-1 inline text-amber-500" />
                            Потребность
                          </div>
                          <div className="mt-1 text-[13px] text-ink">{lead.product}</div>
                        </div>
                      )}
                      {lead.message ? (
                        <div>
                          <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                            Сообщение
                          </div>
                          <div className="mt-1 rounded-lg bg-sunken p-3 text-[13px] text-muted">
                            {lead.message}
                          </div>
                        </div>
                      ) : (
                        <div className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
                          <span className="font-semibold text-faint">пусто · </span>
                          текст обращения отсутствует
                        </div>
                      )}
                    </CardBody>
                  </Card>

                  <Card>
                    <CardHeader>
                      <span aria-hidden>📄</span>
                      <span>Прикреплённые документы</span>
                    </CardHeader>
                    <CardBody>
                      <div className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
                        <span className="font-semibold text-faint">нет данных · </span>
                        вложения (PDF/изображения/файлы) подтянем, когда форма сайта/почты начнёт
                        отдавать <code>attachments[]</code>.
                      </div>
                    </CardBody>
                  </Card>

                  <Card>
                    <CardHeader>
                      <span aria-hidden>💬</span>
                      <span>Переписка</span>
                    </CardHeader>
                    <CardBody>
                      <div className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
                        <span className="font-semibold text-faint">нет данных · </span>
                        история сообщений (WA/TG/Viber/Email) — отдельный фид <code>
                          /api/sales/leads/{id}/messages
                        </code>
                        ; подключим вместе с конвертацией в сделку.
                      </div>
                    </CardBody>
                  </Card>

                  <Card>
                    <CardHeader>
                      <span aria-hidden>✅</span>
                      <span>Задачи по лиду</span>
                    </CardHeader>
                    <CardBody>
                      <div className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
                        <span className="font-semibold text-faint">нет данных · </span>
                        задачи, поставленные из call-popup или вручную — подключим к{" "}
                        <code>fetchDealTasks(`lead:{id}`)</code>.
                      </div>
                    </CardBody>
                  </Card>
                </div>

                {/* RIGHT — контактные данные + AI + распределение */}
                <div className="min-w-0 space-y-4">
                  <Card>
                    <CardHeader>
                      <span aria-hidden>👤</span>
                      <span>Контакт</span>
                    </CardHeader>
                    <CardBody>
                      <dl className="space-y-2 text-[13px]">
                        {lead.name && (
                          <RowKV icon={<User size={13} className="text-muted" />} label="ФИО">
                            {lead.name}
                          </RowKV>
                        )}
                        {lead.phone && (
                          <RowKV icon={<Phone size={13} className="text-muted" />} label="Телефон">
                            <a
                              href={`tel:${lead.phone}`}
                              className="tabular-nums text-accent-ink hover:underline"
                            >
                              {lead.phone}
                            </a>
                          </RowKV>
                        )}
                        {lead.email && (
                          <RowKV icon={<Mail size={13} className="text-muted" />} label="E-mail">
                            <a
                              href={`mailto:${lead.email}`}
                              className="text-accent-ink hover:underline"
                            >
                              {lead.email}
                            </a>
                          </RowKV>
                        )}
                      </dl>
                    </CardBody>
                  </Card>

                  {lead.aiRationale && (
                    <Card>
                      <CardHeader>
                        <span aria-hidden>✦</span>
                        <span>AI-обоснование</span>
                      </CardHeader>
                      <CardBody>
                        <div className="rounded-lg border border-violet-200 bg-violet-50 p-3 text-[13px] text-violet-900">
                          {lead.aiRationale}
                        </div>
                      </CardBody>
                    </Card>
                  )}

                  {lead.assignedTo && (
                    <Card>
                      <CardHeader>
                        <span aria-hidden>🎯</span>
                        <span>Распределение</span>
                      </CardHeader>
                      <CardBody>
                        <div className="text-[13px] text-ink">
                          {lead.assignedTo}
                          {lead.funnel ? ` · ${lead.funnel}` : ""}
                        </div>
                      </CardBody>
                    </Card>
                  )}

                  {lead.dealId && (
                    <Card>
                      <CardBody>
                        <Link
                          href={`/crm/deals/${lead.dealId}`}
                          className="inline-flex items-center gap-1 font-semibold text-money hover:underline"
                        >
                          Открыть сделку → CRM-{lead.dealId}
                        </Link>
                      </CardBody>
                    </Card>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}

function RowKV({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="inline-flex shrink-0 items-center gap-1.5 text-muted">
        {icon}
        {label}
      </span>
      <span className="min-w-0 break-all text-right font-medium text-ink">{children}</span>
    </div>
  );
}
