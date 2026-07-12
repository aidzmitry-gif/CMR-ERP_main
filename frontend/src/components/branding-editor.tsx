"use client";

import { ImageIcon, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { type Branding, fetchBranding, updateBranding } from "@/lib/branding-api";

type Status = "loading" | "error" | "ready";

// Синхронизировано с бэком (_LOGO_MAX_LEN в routes.py): ~1.4МБ data-URI ≈ 1МБ файла.
const MAX_FILE_BYTES = 1_000_000;

/** Ключ поля брендинга — совпадает с ключами {@link Branding} и телом PUT-патча. */
type BrandingField = "logo_data_url" | "stamp_data_url" | "signature_data_url";

interface SlotDef {
  field: BrandingField;
  title: string;
  hint: string;
  emptyLabel: string;
}

// Три изображения печатных форм: лого — в шапку, печать и факсимиле подписи —
// в блок реквизитов счёта И договора (если загружены; иначе честно пустые линии).
const SLOTS: SlotDef[] = [
  {
    field: "logo_data_url",
    title: "Лого",
    hint: "Появится в шапке печатной формы счёта и договора (PNG/JPG/SVG, до ~1000 КБ).",
    emptyLabel: "нет лого",
  },
  {
    field: "stamp_data_url",
    title: "Печать",
    hint: "Оттиск печати организации на счёте и договоре (PNG/SVG с прозрачным фоном, до ~1000 КБ).",
    emptyLabel: "нет печати",
  },
  {
    field: "signature_data_url",
    title: "Подпись руководителя",
    hint: "Факсимиле подписи для печатных форм (PNG/SVG с прозрачным фоном, до ~1000 КБ).",
    emptyLabel: "нет подписи",
  },
];

/**
 * Загрузка изображений брендинга (лого/печать/подпись) для печатных форм счёта и
 * договора. Файл кодируется в data-URI на клиенте (FileReader) — сервер multipart не
 * принимает (см. modules/sales/models.py CompanyBranding, singleton id=1). Каждое
 * изображение обновляется отдельным PUT-патчем (один ключ за раз); повторная загрузка
 * заменяет прежнее.
 */
export function BrandingEditor() {
  const [status, setStatus] = useState<Status>("loading");
  const [branding, setBranding] = useState<Branding>({
    logo_data_url: null,
    stamp_data_url: null,
    signature_data_url: null,
  });

  useEffect(() => {
    void fetchBranding().then((b) => {
      setBranding(b);
      setStatus("ready");
    });
  }, []);

  function handleSaved(field: BrandingField, dataUrl: string) {
    setBranding((prev) => ({ ...prev, [field]: dataUrl }));
  }

  return (
    <div className="space-y-4">
      {status === "loading" && (
        <div className="rounded-xl border border-line bg-sunken p-6 text-sm text-muted">Загрузка…</div>
      )}
      {status === "ready" &&
        SLOTS.map((slot) => (
          <BrandingSlot
            key={slot.field}
            slot={slot}
            value={branding[slot.field]}
            onSaved={(url) => handleSaved(slot.field, url)}
          />
        ))}
    </div>
  );
}

/** Одна карточка загрузки: превью + кнопка «Загрузить/Заменить» + ошибки валидации. */
function BrandingSlot({
  slot,
  value,
  onSaved,
}: {
  slot: SlotDef;
  value: string | null;
  onSaved: (dataUrl: string) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFile(file: File) {
    setError(null);
    if (!file.type.startsWith("image/")) {
      setError("Нужен файл изображения (PNG, JPG, SVG…)");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError(`Файл слишком большой (${Math.round(file.size / 1024)} КБ) — лимит ~1000 КБ`);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result);
      setUploading(true);
      void updateBranding({ [slot.field]: dataUrl }).then((ok) => {
        setUploading(false);
        if (ok) onSaved(dataUrl);
        else setError(`Не удалось сохранить: ${slot.title.toLowerCase()}`);
      });
    };
    reader.onerror = () => setError("Не удалось прочитать файл");
    reader.readAsDataURL(file);
  }

  return (
    <div className="flex items-center gap-4 rounded-xl border border-line p-4">
      <div className="flex h-20 w-52 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-dashed border-line-strong bg-sunken">
        {value ? (
          // eslint-disable-next-line @next/next/no-img-element -- превью data-URI, не статический asset
          <img src={value} alt={slot.title} className="max-h-full max-w-full object-contain" />
        ) : (
          <div className="flex flex-col items-center gap-1 text-faint">
            <ImageIcon size={22} />
            <span className="text-[11px]">{slot.emptyLabel}</span>
          </div>
        )}
      </div>
      <div className="flex-1">
        <div className="text-[13px] font-semibold text-ink">
          {value ? slot.title : `${slot.title} — не загружено`}
        </div>
        <p className="mt-1 text-[12px] text-muted">{slot.hint}</p>
        <button
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="mt-3 inline-flex items-center gap-2 rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-50"
        >
          <Upload size={16} />{" "}
          {uploading ? "Загрузка…" : value ? "Заменить" : "Загрузить"}
        </button>
        {error && <p className="mt-2 text-[12px] text-red-600">{error}</p>}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}
