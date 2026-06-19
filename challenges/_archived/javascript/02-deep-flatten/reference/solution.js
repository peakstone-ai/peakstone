export function flatten(arr) {
  const out = [];
  for (const item of arr) {
    if (Array.isArray(item)) {
      out.push(...flatten(item));
    } else {
      out.push(item);
    }
  }
  return out;
}
