"use client";

import clsx from "clsx";
import { FileText, Truck, UserCheck } from "lucide-react";
import { cloneElement, isValidElement, useState } from "react";

import { OfficeDelivery } from "@/components/erp/office-delivery";
import { OfficeReviewQueue } from "@/components/erp/office-review-queue";

type Tab = "docs" | "delivery" | "reviewers";

function TabButton({
  active,
  onClick,
  icon: Icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ComponentType<{ size?: number }>;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
        active ? "bg-accent-soft text-accent-ink" : "text-muted hover:bg-sunken",
      )}
    >
      <Icon size={16} />
      {children}
    </button>
  );
}

/** Keep the native document funnel mounted when switching workspace tabs. */
export function OfficeView({ board }: { board: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>("docs");
  const [boardRevision, setBoardRevision] = useState(0);
  const refreshedBoard = isValidElement<{ refreshToken?: number }>(board) && typeof board.type === "function"
    ? cloneElement(board, { refreshToken: boardRevision }) : board;

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-line bg-surface px-3 py-2 sm:px-6" aria-label="Разделы офиса">
        <TabButton active={tab === "docs"} onClick={() => setTab("docs")} icon={FileText}>
          Документы
        </TabButton>
        <TabButton
          active={tab === "delivery"}
          onClick={() => setTab("delivery")}
          icon={Truck}
        >
          Доставка
        </TabButton>
        <TabButton active={tab === "reviewers"} onClick={() => setTab("reviewers")} icon={UserCheck}>
          Проверяющие
        </TabButton>
      </div>

      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <div className={tab === "docs" ? "contents" : "hidden"}>{refreshedBoard}</div>
        {tab === "delivery" && <OfficeDelivery onReconciled={() => setBoardRevision(v => v + 1)} />}
        {tab === "reviewers" && <OfficeReviewQueue />}
      </div>
    </div>
  );
}
