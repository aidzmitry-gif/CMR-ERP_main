"use client";

import { Printer } from "lucide-react";
import { useEffect, useState } from "react";

import { code39Bars } from "@/lib/barcode";
import { fetchLocations, locationLabel, type WmsLocation } from "@/lib/wms-ops";

function Barcode({ code }: { code: string }) {
  const { bars, width } = code39Bars(code);
  if (!bars.length) {
    // честный fallback: код не кодируется в Code 39 (напр. кириллица) — показываем читаемо
    return <div className="font-mono text-2xl tracking-widest text-ink">{code}</div>;
  }
  const H = 90;
  return (
    <svg viewBox={`0 0 ${width} ${H}`} width="320" height="90" preserveAspectRatio="none" role="img" aria-label={`Штрихкод ${code}`}>
      {bars.map((b, i) => (
        <rect key={i} x={b.x} y={0} width={b.w} height={H} fill="#000" />
      ))}
    </svg>
  );
}

export function WmsLocationLabel({ id }: { id: number }) {
  const [loc, setLoc] = useState<WmsLocation | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void fetchLocations().then((rows) => {
      setLoc(rows.find((l) => l.id === id) ?? null);
      setLoading(false);
    });
  }, [id]);

  if (loading) return <div className="p-6 text-muted">Загрузка…</div>;
  if (!loc) return <div className="p-6 text-muted">Ячейка не найдена</div>;

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="mb-4 flex items-center gap-2 print:hidden">
        <button
          onClick={() => window.print()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink"
        >
          <Printer size={15} /> Печать
        </button>
        <span className="text-xs text-faint">
          Code 39 для ASCII-кода ячейки; неподдерживаемые символы — читаемым текстом.
        </span>
      </div>

      <div className="mx-auto flex w-[360px] flex-col items-center gap-3 rounded-xl border border-line bg-surface p-6 print:border-black">
        <div className="text-xs uppercase tracking-wide text-muted">{loc.warehouse}</div>
        <div className="text-3xl font-bold tabular-nums text-ink">{locationLabel(loc)}</div>
        <Barcode code={loc.code} />
        <div className="font-mono text-sm text-muted">{loc.code}</div>
        {loc.title && <div className="text-sm text-muted">{loc.title}</div>}
      </div>
    </div>
  );
}
