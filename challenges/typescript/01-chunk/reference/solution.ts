export function chunk<T>(arr: T[], size: number): T[][] {
  if (size < 1) throw new RangeError("size must be >= 1");
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    out.push(arr.slice(i, i + size));
  }
  return out;
}
