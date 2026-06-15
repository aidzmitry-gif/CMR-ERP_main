import type { DuplicateCluster, DuplicateMember } from "./reference-data";

/** Первый член кластера — эталон (golden record / survivor). */
export function clusterSurvivor(cluster: DuplicateCluster): DuplicateMember | undefined {
  return cluster.members[0];
}

/** Все члены кластера кроме первого — кандидаты на слияние. */
export function clusterDuplicates(cluster: DuplicateCluster): DuplicateMember[] {
  return cluster.members.slice(1);
}
