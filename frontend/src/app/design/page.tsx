import { Button, Card, CardHeader, CardBody, Badge } from "@/components/ui";
import { Phone, PhoneOff, Plus, Sparkles, CreditCard, Trash2, Check } from "lucide-react";

/**
 * Витрина дизайн-системы — живой каталог компонентов ui.
 * По мере роста components/ui сюда добавляются Card, Badge, Table и т.д.
 * Открыть: /design
 */
export default function DesignSystemPage() {
  return (
    <main className="mx-auto max-w-[1100px] p-8 space-y-10">
      <header>
        <p className="text-xs font-semibold uppercase tracking-wide text-faint">Дизайн-система · Stripe/Notion</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Каталог компонентов UI</h1>
        <p className="mt-1 text-sm text-muted">
          Единые примитивы на токенах. Кнопка заменяет инлайн-классы по проекту. Варианты служат
          приоритетам платформы: money/call — деньги (№1), danger/hangup отделяют необратимое (№2).
        </p>
      </header>

      <Section title="Button · варианты (иерархия)">
        <Row>
          <Button variant="primary" icon={<Plus />}>Новая сделка</Button>
          <Button variant="secondary">Фильтр</Button>
          <Button variant="ghost">Экспорт</Button>
        </Row>
        <Row>
          <Button variant="money" icon={<CreditCard />}>Запросить доплату</Button>
          <Button variant="violet" icon={<Sparkles />}>Спросить AI</Button>
          <Button variant="danger" icon={<Trash2 />}>Удалить</Button>
        </Row>
        <Row>
          <Button variant="call" icon={<Phone />}>Позвонить</Button>
          <Button variant="hangup" icon={<PhoneOff />}>Завершить</Button>
          <Button variant="money" icon={<Check />}>Перевести в «Защищён»</Button>
        </Row>
      </Section>

      <Section title="Button · размеры">
        <Row>
          <Button size="lg" variant="money" icon={<CreditCard />}>Hero — крупное действие</Button>
          <Button size="md" variant="primary">Medium (по умолчанию)</Button>
          <Button size="sm" variant="secondary">Small</Button>
        </Row>
      </Section>

      <Section title="Button · состояния">
        <Row>
          <Button variant="primary">Обычная</Button>
          <Button variant="primary" disabled>Заблокирована</Button>
          <Button variant="primary" block>На всю ширину (block)</Button>
        </Row>
      </Section>

      <Section title="Badge · тоны (по смыслу)">
        <Row>
          <Badge tone="emerald">Оплачен</Badge>
          <Badge tone="teal">Прогноз</Badge>
          <Badge tone="amber">Ждёт согласования</Badge>
          <Badge tone="red">Дебиторка</Badge>
          <Badge tone="violet">AI-инсайт</Badge>
          <Badge tone="accent">Стадия: Счёт</Badge>
          <Badge tone="slate">Черновик</Badge>
        </Row>
      </Section>

      {/* Собрано из примитивов — реальный фрагмент карточки сделки */}
      <section>
        <h2 className="mb-4 text-[11px] font-semibold uppercase tracking-wide text-faint">
          Собрано из примитивов · фрагмент карточки сделки
        </h2>
        <Card className="max-w-[520px]">
          <CardHeader>
            <span>📦 ООО «БелТранс» — поставка АКБ</span>
            <Badge tone="amber" className="ml-auto">4 дня в стадии</Badge>
          </CardHeader>
          <CardBody className="space-y-3">
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-muted">Маржа сделки · прибыль</span>
              <span className="text-xl font-bold tabular-nums text-money">+12 400 BYN</span>
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-muted">Сумма · оплачено</span>
              <span className="text-sm font-semibold tabular-nums">46 800 · 20 000 BYN</span>
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              <Badge tone="emerald">★ Постоянный клиент</Badge>
              <Badge tone="accent">Стадия: Счёт</Badge>
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              <Button variant="money" size="sm" icon={<CreditCard />}>Запросить доплату</Button>
              <Button variant="call" size="sm" icon={<Phone />}>Позвонить</Button>
              <Button variant="ghost" size="sm">Открыть</Button>
            </div>
          </CardBody>
        </Card>
      </section>
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-6 shadow-card">
      <h2 className="mb-4 text-[11px] font-semibold uppercase tracking-wide text-faint">{title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center gap-3">{children}</div>;
}
