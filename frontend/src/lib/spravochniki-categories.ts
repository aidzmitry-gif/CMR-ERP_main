import type { NomenclatureGroup } from "@/lib/reference-data";

/** Глубина узла в дереве (корень = 1). */
export function getNodeDepth(id: number, groups: NomenclatureGroup[]): number {
  const byId = new Map(groups.map((g) => [g.id, g]));
  let depth = 1;
  let node = byId.get(id);
  while (node?.parent_id != null) {
    node = byId.get(node.parent_id);
    depth++;
  }
  return depth;
}

/** Путь от корня до узла (имена, первый = корень). */
export function buildBreadcrumb(id: number, groups: NomenclatureGroup[]): string[] {
  const byId = new Map(groups.map((g) => [g.id, g]));
  const path: string[] = [];
  let node = byId.get(id);
  while (node) {
    path.unshift(node.name);
    node = node.parent_id != null ? byId.get(node.parent_id) : undefined;
  }
  return path;
}

/** Все ID потомков узла рекурсивно (сам id не включается). */
export function getDescendantIds(id: number, groups: NomenclatureGroup[]): Set<number> {
  const result = new Set<number>();
  const queue = [id];
  while (queue.length > 0) {
    const cur = queue.shift()!;
    for (const g of groups) {
      if (g.parent_id === cur) {
        result.add(g.id);
        queue.push(g.id);
      }
    }
  }
  return result;
}

/**
 * Фильтр плоского списка по подстроке (имя или код).
 * Возвращает совпавшие узлы + их предков (чтобы путь в дереве был видимым).
 */
export function filterFlatGroups(
  groups: NomenclatureGroup[],
  query: string,
): NomenclatureGroup[] {
  if (!query.trim()) return groups;
  const q = query.toLowerCase();
  const matched = new Set(
    groups
      .filter((g) => g.name.toLowerCase().includes(q) || g.code.toLowerCase().includes(q))
      .map((g) => g.id),
  );
  const byId = new Map(groups.map((g) => [g.id, g]));
  const withAncestors = new Set(matched);
  for (const id of matched) {
    let node = byId.get(id);
    while (node?.parent_id != null) {
      withAncestors.add(node.parent_id);
      node = byId.get(node.parent_id);
    }
  }
  return groups.filter((g) => withAncestors.has(g.id));
}
