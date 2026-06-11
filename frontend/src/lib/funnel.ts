import type { Stage } from "@/lib/types";

export interface FunnelData {
  activeCount: number;
  activeSum: number;
  wonCount: number;
  wonSum: number;
  lostCount: number;
  lostSum: number;
  /** Win rate = won / (won + lost), %. Сделки «в работе» в знаменатель НЕ входят. */
  conversion: number;
}

/** Агрегаты воронки из стадий доски (реальные данные, считаются на клиенте).
 *
 * `lost` — отдельный закрытый бакет (проигрыш): он НЕ попадает в «в работе», иначе
 * «Сумма/сделок в работе» завышается. Конверсия — win rate среди закрытых сделок
 * (won / (won + lost)), а не доля от всей воронки (SALES-40). */
export function computeFunnel(
  stages: Stage[],
  wonStageId = "won",
  lostStageId = "lost",
): FunnelData {
  let activeCount = 0;
  let activeSum = 0;
  let wonCount = 0;
  let wonSum = 0;
  let lostCount = 0;
  let lostSum = 0;

  for (const s of stages) {
    if (s.id === wonStageId) {
      wonCount += s.count;
      wonSum += s.sum;
    } else if (s.id === lostStageId) {
      lostCount += s.count;
      lostSum += s.sum;
    } else {
      activeCount += s.count;
      activeSum += s.sum;
    }
  }

  const closed = wonCount + lostCount;
  return {
    activeCount,
    activeSum,
    wonCount,
    wonSum,
    lostCount,
    lostSum,
    conversion: closed ? (wonCount / closed) * 100 : 0,
  };
}
