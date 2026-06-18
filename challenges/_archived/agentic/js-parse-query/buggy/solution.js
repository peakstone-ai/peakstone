export function parseQuery(qs) {
  const out = {};
  for (const part of qs.split("&")) {
    const [k, v] = part.split("=");
    out[k] = v;
  }
  return out;
}
