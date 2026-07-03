"use client";

import { ImageIcon, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fetchBranding, updateBranding } from "@/lib/api";

type Status = "loading" | "error" | "ready";

// Синхронизировано с бэком (_LOGO_MAX_LEN в routes.py): ~1.4МБ data-URI ≈ 1МБ файла.
const MAX_FILE_BYTES = 1_000_000;

/**
 * Загрузка лого продавца для печатных форм (счёт-протокол/договор). Файл кодируется в
 * data-URI на клиенте (FileReader) — сервер multipart не принимает, в проекте нет
 * установившегося паттерна загрузки бинарных файлов (см. modules/sales/models.py
 * CompanyBranding). Один файл на компанию — повторная загрузка заменяет прежний.
 */
export function BrandingEditor() {
  const [status, setStatus] = useState<Status>("loading");
  const [logo, setLogo] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void fetchBranding().then((url) => {
      setLogo(url);
      setStatus("ready");
    });
  }, []);

  function handlePick() {
    inputRef.current?.click();
  }

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
      void updateBranding(dataUrl).then((ok) => {
        setUploading(false);
        if (ok) {
          setLogo(dataUrl);
        } else {
          setError("Не удалось сохранить лого");
        }
      });
    };
    reader.onerror = () => setError("Не удалось прочитать файл");
    reader.readAsDataURL(file);
  }

  return (
    <div className="space-y-4">
      {status === "loading" && (
        <div className="rounded-xl border border-line bg-sunken p-6 text-sm text-muted">Загрузка…</div>
      )}
      {status === "ready" && (
        <>
          <div className="flex items-center gap-4 rounded-xl border border-line p-4">
            <div className="flex h-20 w-52 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-dashed border-line-strong bg-sunken">
              {logo ? (
                // eslint-disable-next-line @next/next/no-img-element -- превью data-URI, не статический asset
                <img src={logo} alt="Лого продавца" className="max-h-full max-w-full object-contain" />
              ) : (
                <div className="flex flex-col items-center gap-1 text-faint">
                  <ImageIcon size={22} />
                  <span className="text-[11px]">нет лого</span>
                </div>
              )}
            </div>
            <div className="flex-1">
              <div className="text-[13px] font-semibold text-ink">
                {logo ? "Текущее лого" : "Лого не загружено"}
              </div>
              <p className="mt-1 text-[12px] text-muted">
                Появится в шапке печатной формы счёта (PNG/JPG/SVG, до ~1000 КБ).
              </p>
              <button
                onClick={handlePick}
                disabled={uploading}
                className="mt-3 inline-flex items-center gap-2 rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-50"
              >
                <Upload size={16} /> {uploading ? "Загрузка…" : logo ? "Заменить лого" : "Загрузить лого"}
              </button>
              {error && <p className="mt-2 text-[12px] text-red-600">{error}</p>}
            </div>
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
        </>
      )}
    </div>
  );
}
