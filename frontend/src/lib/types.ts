export type Priority = "Высокий" | "Средний" | "Низкий";

export type ChannelKey = "phone" | "whatsapp" | "viber" | "telegram" | "email";

export interface Deal {
  id: string;
  number: string;
  company: string;
  description: string;
  amount: number;
  priority: Priority;
  owner: string;
  date?: string;
  nextStep?: string;
  closedDate?: string;
  starred?: boolean;
  // развёрнутый блок «что нужно сделать» (как у карточки в стадии КП на макете)
  todo?: string;
  actionTime?: string;
  actionDate?: string;
  itemsLabel?: string;
  itemsCount?: number;
}

export interface Stage {
  id: string;
  title: string;
  color: string;
  count: number;
  sum: number;
  deals: Deal[];
}

export type KpiIcon = "phone-key" | "phone" | "ruble" | "snow" | "doc";
export type KpiTone = "blue" | "indigo" | "green" | "cyan" | "slate";

export interface Kpi {
  id: string;
  label: string;
  value: number;
  target: number;
  percent: number;
  money?: boolean;
  icon: KpiIcon;
  tone: KpiTone;
}

export type ChatKind = "person" | "logistics" | "purchasing" | "warehouse";

export interface Chat {
  id: string;
  name: string;
  time: string;
  message: string;
  unread?: number;
  kind: ChatKind;
}

export interface FunnelTotal {
  id: string;
  label: string;
  value: string;
  delta: string;
}

export interface DealMessage {
  from: string;
  channel: ChannelKey;
  time: string;
  text: string;
}

export interface DealItemView {
  title: string;
  lastPrice?: number;
  minPrice?: number;
}

export interface DealDetail {
  number: string;
  company: string;
  description: string;
  amount: number;
  priority: Priority;
  nextStep: string;
  contact: string;
  datetime: string;
  itemsTitle: string;
  items: DealItemView[];
  messages: DealMessage[];
  focus: boolean;
  starred: boolean;
  dealDate: string;
}

export type LeadStatus = "new" | "qualified" | "routed" | "converted" | "rejected";

export interface Lead {
  id: number;
  source: string; // site|telegram|whatsapp|email|phone|tender
  name: string;
  company: string;
  phone?: string;
  email?: string;
  region: string;
  product: string;
  message: string;
  status: LeadStatus;
  score: number;
  qualification: string; // "" | "target" | "non-target"
  reason: string;
  assignedTo: string;
  funnel: string; // "" | new | regular | tender | project
  dealId?: number;
  aiRationale?: string; // обоснование AI-квалификатора (если AI включён)
}
