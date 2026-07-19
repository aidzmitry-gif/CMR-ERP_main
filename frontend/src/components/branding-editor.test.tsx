import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Компонент тестируем изолированно от сети — мокаем branding-api (fetch/PUT).
vi.mock("@/lib/branding-api", () => ({
  fetchBranding: vi.fn(),
  updateBranding: vi.fn(),
}));

import { BrandingEditor } from "@/components/branding-editor";
import * as brandingApi from "@/lib/branding-api";

const EMPTY = { logo_data_url: null, stamp_data_url: null, signature_data_url: null };

function mockFetch(value: Partial<typeof EMPTY> = {}) {
  (brandingApi.fetchBranding as ReturnType<typeof vi.fn>).mockResolvedValue({ ...EMPTY, ...value });
}

// Один из трёх скрытых <input type=file> по индексу слота (0=лого,1=печать,2=подпись).
function fileInput(index: number): HTMLInputElement {
  return document.querySelectorAll<HTMLInputElement>('input[type="file"]')[index];
}

beforeEach(() => {
  vi.clearAllMocks();
  mockFetch();
  (brandingApi.updateBranding as ReturnType<typeof vi.fn>).mockResolvedValue(true);
});

describe("BrandingEditor", () => {
  it("показывает «Загрузка…» пока не разрешился fetchBranding и убирает после", async () => {
    let resolve!: (v: typeof EMPTY) => void;
    (brandingApi.fetchBranding as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    render(<BrandingEditor />);
    // до разрешения промиса — состояние loading, слотов ещё нет
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
    expect(screen.queryByText(/не загружено/)).not.toBeInTheDocument();

    resolve(EMPTY);
    await waitFor(() => expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument());
    expect(await screen.findByText("Лого — не загружено")).toBeInTheDocument();
  });

  it("в состоянии ready рендерит три слота с русскими заголовками и подсказками", async () => {
    render(<BrandingEditor />);
    // все пустые → заголовки в форме «… — не загружено»
    expect(await screen.findByText("Лого — не загружено")).toBeInTheDocument();
    expect(screen.getByText("Печать — не загружено")).toBeInTheDocument();
    expect(screen.getByText("Подпись руководителя — не загружено")).toBeInTheDocument();
    // пустые превью показывают emptyLabel и кнопку «Загрузить», а не «Заменить»
    expect(screen.getByText("нет лого")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Загрузить/ })).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Заменить" })).not.toBeInTheDocument();
  });

  it("уже загруженное изображение показывает превью и кнопку «Заменить»", async () => {
    mockFetch({ logo_data_url: "data:image/png;base64,AAA" });
    render(<BrandingEditor />);
    // слот лого не пустой → заголовок без «не загружено», есть <img> с data-URI
    expect(await screen.findByText("Лого")).toBeInTheDocument();
    const img = screen.getByAltText("Лого") as HTMLImageElement;
    expect(img).toHaveAttribute("src", "data:image/png;base64,AAA");
    // на его карточке — «Заменить»; на пустых печати/подписи — «Загрузить»
    expect(screen.getByRole("button", { name: /Заменить/ })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Загрузить/ })).toHaveLength(2);
  });

  it("загрузка валидного файла шлёт updateBranding нужным ключом и обновляет превью", async () => {
    render(<BrandingEditor />);
    await screen.findByText("Лого — не загружено");

    const file = new File(["hello"], "logo.png", { type: "image/png" });
    fireEvent.change(fileInput(0), { target: { files: [file] } });

    // FileReader кодирует в data-URI асинхронно → ждём вызов PUT только по ключу лого
    await waitFor(() => expect(brandingApi.updateBranding).toHaveBeenCalledTimes(1));
    const patch = (brandingApi.updateBranding as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(Object.keys(patch)).toEqual(["logo_data_url"]);
    expect(patch.logo_data_url).toMatch(/^data:image\/png/);

    // после успеха превью появилось и кнопка стала «Заменить»
    expect(await screen.findByAltText("Лого")).toBeInTheDocument();
  });

  it("не-изображение отклоняется с ошибкой и без обращения к бэку", async () => {
    render(<BrandingEditor />);
    await screen.findByText("Лого — не загружено");

    const bad = new File(["text"], "notes.txt", { type: "text/plain" });
    fireEvent.change(fileInput(0), { target: { files: [bad] } });

    expect(await screen.findByText(/Нужен файл изображения/)).toBeInTheDocument();
    expect(brandingApi.updateBranding).not.toHaveBeenCalled();
  });

  it("файл больше лимита ~1000 КБ отклоняется с ошибкой и не шлётся на бэк", async () => {
    render(<BrandingEditor />);
    await screen.findByText("Лого — не загружено");

    // 1 000 001 байт > MAX_FILE_BYTES (1 000 000)
    const big = new File([new Uint8Array(1_000_001)], "big.png", { type: "image/png" });
    fireEvent.change(fileInput(0), { target: { files: [big] } });

    expect(await screen.findByText(/Файл слишком большой/)).toBeInTheDocument();
    expect(brandingApi.updateBranding).not.toHaveBeenCalled();
  });

  it("сбой сохранения показывает ошибку и не рисует превью (лид не считается сохранённым)", async () => {
    (brandingApi.updateBranding as ReturnType<typeof vi.fn>).mockResolvedValue(false);
    render(<BrandingEditor />);
    await screen.findByText("Печать — не загружено");

    const file = new File(["x"], "stamp.png", { type: "image/png" });
    fireEvent.change(fileInput(1), { target: { files: [file] } }); // слот печати

    // ошибка именно по печати; превью не появилось
    expect(await screen.findByText("Не удалось сохранить: печать")).toBeInTheDocument();
    expect(screen.queryByAltText("Печать")).not.toBeInTheDocument();
    // слот печати всё ещё «не загружено»
    expect(screen.getByText("Печать — не загружено")).toBeInTheDocument();
  });

  it("во время сохранения кнопка блокируется и показывает «Загрузка…»", async () => {
    let resolveSave!: (ok: boolean) => void;
    (brandingApi.updateBranding as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise((r) => {
        resolveSave = r;
      }),
    );
    render(<BrandingEditor />);
    await screen.findByText("Лого — не загружено");

    const file = new File(["x"], "logo.png", { type: "image/png" });
    fireEvent.change(fileInput(0), { target: { files: [file] } });

    // пока PUT висит — кнопка слота лого disabled и текст «Загрузка…»
    const logoCard = screen.getByText("Лого — не загружено").closest("div")?.parentElement as HTMLElement;
    const btn = await within(logoCard).findByRole("button", { name: "Загрузка…" });
    expect(btn).toBeDisabled();

    resolveSave(true);
    await waitFor(() => expect(within(logoCard).queryByRole("button", { name: "Загрузка…" })).not.toBeInTheDocument());
  });
});
