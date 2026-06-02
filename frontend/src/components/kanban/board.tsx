import { Column } from "@/components/kanban/column";
import type { Stage } from "@/lib/types";

export function Board({ stages }: { stages: Stage[] }) {
  return (
    <div className="flex gap-4 overflow-x-auto pb-2 thin-scroll">
      {stages.map((stage) => (
        <Column key={stage.id} stage={stage} />
      ))}
    </div>
  );
}
