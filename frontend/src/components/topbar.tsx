import { Bell, HelpCircle, MessageSquareText } from "lucide-react";

function IconButton({ children, badge }: { children: React.ReactNode; badge?: number }) {
  return (
    <button className="relative flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100">
      {children}
      {badge !== undefined && (
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
          {badge}
        </span>
      )}
    </button>
  );
}

export function Topbar({ crumbs }: { crumbs: string[] }) {
  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6">
      <h1 className="text-xl font-bold">
        <span className="font-semibold text-muted">{crumbs[0]}</span>
        {crumbs[1] && <span className="px-1.5 text-slate-300">/</span>}
        {crumbs[1] && <span className="text-ink">{crumbs[1]}</span>}
      </h1>
      <div className="flex items-center gap-2">
        <IconButton badge={0}>
          <Bell size={19} />
        </IconButton>
        <IconButton>
          <MessageSquareText size={19} />
        </IconButton>
        <IconButton>
          <HelpCircle size={19} />
        </IconButton>
        <span className="ml-1 flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-slate-500 to-slate-700 text-xs font-semibold text-white">
          ИП
        </span>
      </div>
    </header>
  );
}
