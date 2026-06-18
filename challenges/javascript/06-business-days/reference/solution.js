import { parseISO, eachDayOfInterval, isWeekend } from "date-fns";

export function businessDaysBetween(startISO, endISO) {
  const start = parseISO(startISO);
  const end = parseISO(endISO);
  if (end <= start) return 0;
  // eachDayOfInterval is inclusive of both ends; drop the start (index 0)
  // to make the range exclusive of start and inclusive of end.
  return eachDayOfInterval({ start, end })
    .slice(1)
    .filter((day) => !isWeekend(day)).length;
}
