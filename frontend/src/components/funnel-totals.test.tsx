import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FunnelTotals } from "@/components/funnel-totals";

describe("FunnelTotals", () => {
  it("показывает агрегаты воронки и конверсию", () => {
    render(<FunnelTotals data={{ activeCount: 5, activeSum: 1000, wonCount: 2, wonSum: 500, conversion: 28.57 }} />);
    expect(screen.getByText("Итоги по воронке")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("28.6%")).toBeInTheDocument();
  });
});
