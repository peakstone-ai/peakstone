import { compile } from "mathjs";

export function evaluateAll(expr, scopes) {
  const code = compile(expr);
  return scopes.map((scope) => code.evaluate(scope));
}
