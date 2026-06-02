import { Column } from "@/components/kanban/column";
import { STAGES } from "@/lib/mock-data";

export function Board() {
  return (
    <div className="flex gap-4 overflow-x-auto pb-2 thin-scroll">
      {STAGES.map((stage) => (
        <Column key={stage.id} stage={stage} />
      ))}
    </div>
  );
}
