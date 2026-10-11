// Year groups for the problem of the week. Juniors are 4th to 6th, seniors L8th and U8th.

export const YEAR_GROUPS = [
  { id: "4", label: "4th" },
  { id: "5", label: "5th" },
  { id: "6", label: "6th" },
  { id: "L8", label: "L8th" },
  { id: "U8", label: "U8th" },
] as const;

export type YearGroup = (typeof YEAR_GROUPS)[number]["id"];

export function yearLabel(id: string | null | undefined): string {
  return YEAR_GROUPS.find((y) => y.id === id)?.label ?? "–";
}

/** Someone who has entered, as the admin People pages see them. */
export interface Person {
  email: string;
  name: string;
  year_group: string | null;
  banned: boolean;
  weeks: number;
  entries: number;
  joined_at: string;
  last_entry_at: string | null;
}
