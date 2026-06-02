import type { Stage } from "@/lib/types";

export interface FunnelData {
  activeCount: number;
  activeSum: number;
  wonCount: number;
  wonSum: number;
  conversion: number;
}

/** Агрегаты воронки из стадий доски (реальные данные, считаются на клиенте). */
export function computeFunnel(stages: Stage[], wonStageId = "won"): FunnelData {
  let activeCount = 0;
  let activeSum = 0;
  let wonCount = 0;
  let wonSum = 0;
  let totalCount = 0;

  for (const s of stages) {
    totalCount += s.count;
    if (s.id === wonStageId) {
      wonCount += s.count;
      wonSum += s.sum;
    } else {
      activeCount += s.count;
      activeSum += s.sum;
    }
  }

  return {
    activeCount,
    activeSum,
    wonCount,
    wonSum,
    conversion: totalCount ? (wonCount / totalCount) * 100 : 0,
  };
}
