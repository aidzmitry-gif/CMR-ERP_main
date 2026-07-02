// Минимальный кодер Code 39 (без внешних зависимостей) для печатных этикеток ячеек.
// Code 39 кодирует A–Z, 0–9 и - . $ / + % пробел — этого хватает для кодов ячеек (A-01-02).
// Не-ASCII (кириллица в номерах приёмки) не кодируется → вызывающий показывает читаемый код.

const PATTERNS: Record<string, string> = {
  "0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw", "3": "wnwwnnnnn", "4": "nnnwwnnnw",
  "5": "wnnwwnnnn", "6": "nnwwwnnnn", "7": "nnnwnnwnw", "8": "wnnwnnwnn", "9": "nnwwnnwnn",
  A: "wnnnnwnnw", B: "nnwnnwnnw", C: "wnwnnwnnn", D: "nnnnwwnnw", E: "wnnnwwnnn",
  F: "nnwnwwnnn", G: "nnnnnwwnw", H: "wnnnnwwnn", I: "nnwnnwwnn", J: "nnnnwwwnn",
  K: "wnnnnnnww", L: "nnwnnnnww", M: "wnwnnnnwn", N: "nnnnwnnww", O: "wnnnwnnwn",
  P: "nnwnwnnwn", Q: "nnnnnnwww", R: "wnnnnnwwn", S: "nnwnnnwwn", T: "nnnnwnwwn",
  U: "wwnnnnnnw", V: "nwwnnnnnw", W: "wwwnnnnnn", X: "nwnnwnnnw", Y: "wwnnwnnnn",
  Z: "nwwnwnnnn", "-": "nwnnnnwnw", ".": "wwnnnnwnn", " ": "nwwnnnwnn", "*": "nwnnwnwnn",
  $: "nwnwnwnnn", "/": "nwnwnnnwn", "+": "nwnnnwnwn", "%": "nnnwnwnwn",
};

export interface Bar {
  x: number;
  w: number;
}

/** Кодируемо ли значение в Code 39 (все символы в таблице, в верхнем регистре). */
export function isCode39(text: string): boolean {
  return text.length > 0 && text.toUpperCase().split("").every((c) => c in PATTERNS && c !== "*");
}

/**
 * Чёрные штрихи Code 39 для значения. narrow=1, wide=3 модуля; между символами — узкий пробел.
 * Возвращает {bars, width} в модульных единицах. Пустой при некодируемом значении.
 */
export function code39Bars(text: string, narrow = 2, wide = 6): { bars: Bar[]; width: number } {
  if (!isCode39(text)) return { bars: [], width: 0 };
  const chars = `*${text.toUpperCase()}*`;
  const bars: Bar[] = [];
  let x = 0;
  chars.split("").forEach((ch, idx) => {
    const pat = PATTERNS[ch];
    for (let i = 0; i < pat.length; i++) {
      const w = pat[i] === "w" ? wide : narrow;
      if (i % 2 === 0) bars.push({ x, w }); // чётные элементы — штрихи (бар)
      x += w;
    }
    if (idx < chars.length - 1) x += narrow; // межсимвольный узкий пробел
  });
  return { bars, width: x };
}
