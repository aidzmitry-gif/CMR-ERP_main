import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PriorityBadge } from "@/components/priority-badge";

describe("PriorityBadge", () => {
  it("показывает текст приоритета", () => {
    render(<PriorityBadge priority="Высокий" />);
    expect(screen.getByText("Высокий")).toBeInTheDocument();
  });

  it("применяет цветовой класс по приоритету", () => {
    render(<PriorityBadge priority="Низкий" />);
    expect(screen.getByText("Низкий").className).toContain("text-slate-500");
  });

  it("показывает иконку при withIcon", () => {
    const { container } = render(<PriorityBadge priority="Средний" withIcon />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
