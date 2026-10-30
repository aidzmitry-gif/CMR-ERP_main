/** Initials of the signed-in user, shared by both profile links. */
export function userInitials(name: string): string {
  return name
    .replace(/[«».·/]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase() || "?";
}
