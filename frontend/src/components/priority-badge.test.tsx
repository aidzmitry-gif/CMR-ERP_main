import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PriorityBadge } from "@/components/priority-badge";

describe("PriorityBadge", () => {
  it("показывает текст приоритета", () => {
    render(<PriorityBadge priority="Высокий" />);
    expect(screen.getByText("Высокий")).toBeInTheDocument();
  });

  it("применяет цветовой класс по приоритету", () => {
    // «Низкий» приоритет в DESIGN.md §1 = нейтраль (sunken+muted), не slate-500 (legacy).
    render(<PriorityBadge priority="Низкий" />);
    expect(screen.getByText("Низкий").className).toContain("text-muted");
  });

  it("показывает иконку при withIcon", () => {
    const { container } = render(<PriorityBadge priority="Средний" withIcon />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
