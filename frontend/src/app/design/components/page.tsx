"use client";

import { useState } from "react";
import {
  Button, Card, Badge, Input, Textarea, Select, Field, Checkbox, Switch,
  Table, Th, Td, Tr, EmptyState, LoadingRows, ErrorState, Tabs, Modal, Drawer, Tooltip,
} from "@/components/ui";
import { Search, Inbox, Info, Plus } from "lucide-react";

/** Витрина оставшихся компонентов дизайн-системы — для согласования. Открыть: /design/components */
export default function ComponentsPage() {
  const [modal, setModal] = useState(false);
  const [drawer, setDrawer] = useState(false);

  return (
    <main className="mx-auto max-w-[1100px] space-y-8 p-8">
      <header>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">Дизайн-система · оставшиеся компоненты</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Формы, таблица, окна, состояния</h1>
        <p className="mt-1 text-sm text-muted">Всё на токенах Stripe/Notion. Согласуем — и дизайн-система полная.</p>
      </header>

      {/* Поля ввода */}
      <Section title="Поля ввода (Input / Select / Textarea)">
        <div className="grid max-w-2xl gap-4 sm:grid-cols-2">
          <Field label="Название" required hint="Как в счёте">
            <Input placeholder="ООО «БелТранс»" />
          </Field>
          <Field label="Поиск">
            <Input icon={<Search />} placeholder="Поиск сделок..." />
          </Field>
          <Field label="Стадия">
            <Select defaultValue="">
              <option value="" disabled>Выберите…</option>
              <option>Квалификация</option>
              <option>Счёт</option>
              <option>Договор</option>
            </Select>
          </Field>
          <Field label="Сумма, BYN" error="Должно быть больше 0">
            <Input invalid defaultValue="0" />
          </Field>
          <Field label="Комментарий" hint="Виден всей команде">
            <Textarea placeholder="Заметка по сделке…" />
          </Field>
          <Field label="Отключено">
            <Input disabled defaultValue="нельзя редактировать" />
          </Field>
        </div>
      </Section>

      {/* Чекбоксы и переключатели */}
      <Section title="Checkbox / Switch">
        <div className="flex flex-wrap items-center gap-6">
          <Checkbox label="Постоянный клиент" defaultChecked />
          <Checkbox label="Высокий приоритет" />
          <Switch label="Уведомления в Telegram" defaultChecked />
          <Switch label="Скрыть закрытые" />
        </div>
      </Section>

      {/* Вкладки */}
      <Section title="Tabs">
        <Tabs
          tabs={[
            { label: "Обзор", content: <p className="text-sm text-muted">Контент вкладки «Обзор».</p> },
            { label: "Деньги", content: <p className="text-sm text-muted">Контент вкладки «Деньги».</p> },
            { label: "Активность", content: <p className="text-sm text-muted">Контент вкладки «Активность».</p> },
          ]}
        />
      </Section>

      {/* Таблица */}
      <Section title="Table">
        <Card className="overflow-hidden">
          <Table>
            <thead>
              <tr>
                <Th>Клиент</Th>
                <Th className="text-right">Сумма</Th>
                <Th className="text-right">Маржа</Th>
                <Th>Статус</Th>
              </tr>
            </thead>
            <tbody>
              {[
                ["ООО «БелТранс»", "46 800", "+12 400", "emerald", "Оплачен"],
                ["ООО ХимПром", "140 000", "+28 000", "red", "Дебиторка"],
                ["ИП СтройКомплекс", "42 000", "+6 300", "amber", "Ждёт"],
              ].map(([c, s, m, tone, label]) => (
                <Tr key={c}>
                  <Td>{c}</Td>
                  <Td className="text-right tabular-nums">{s} BYN</Td>
                  <Td className="text-right font-semibold tabular-nums text-money">{m}</Td>
                  <Td><Badge tone={tone as "emerald"}>{label}</Badge></Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        </Card>
      </Section>

      {/* Окна */}
      <Section title="Modal / Drawer / Tooltip">
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => setModal(true)}>Открыть модалку</Button>
          <Button variant="secondary" onClick={() => setDrawer(true)}>Открыть drawer</Button>
          <Tooltip text="Подсказка при наведении">
            <Button variant="ghost" icon={<Info />}>Наведи на меня</Button>
          </Tooltip>
        </div>
      </Section>

      {/* Состояния */}
      <Section title="Состояния: пусто / загрузка / ошибка">
        <div className="grid gap-4 lg:grid-cols-3">
          <Card><EmptyState icon={<Inbox />} title="Пока пусто" hint="Нет сделок по фильтру." action={<Button size="sm" icon={<Plus />}>Создать</Button>} /></Card>
          <Card><LoadingRows /></Card>
          <Card><ErrorState hint="Backend недоступен." action={<Button size="sm" variant="secondary">Повторить</Button>} /></Card>
        </div>
      </Section>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title="Создать сделку"
        footer={<>
          <Button variant="ghost" onClick={() => setModal(false)}>Отмена</Button>
          <Button onClick={() => setModal(false)}>Создать</Button>
        </>}
      >
        <div className="space-y-3">
          <Field label="Клиент" required><Input placeholder="Название компании" /></Field>
          <Field label="Сумма, BYN"><Input defaultValue="0" /></Field>
        </div>
      </Modal>

      <Drawer open={drawer} onClose={() => setDrawer(false)} title="CRM-1029 · ООО «БелТранс»">
        <div className="space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-muted">Маржа</span><b className="text-money tabular-nums">+12 400 BYN</b></div>
          <div className="flex justify-between"><span className="text-muted">Сумма</span><b className="tabular-nums">46 800 BYN</b></div>
          <div className="flex gap-2 pt-2">
            <Badge tone="emerald">★ Постоянный</Badge>
            <Badge tone="accent">Стадия: Счёт</Badge>
          </div>
        </div>
      </Drawer>
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-6 shadow-card">
      <h2 className="mb-4 text-[11px] font-semibold uppercase tracking-wide text-faint">{title}</h2>
      {children}
    </section>
  );
}
