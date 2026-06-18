import { compile } from "mathjs";

export function evaluateAll(expr: string, scopes: Record<string, number>[]): number[] {
  const compiled = compile(expr);
  return scopes.map((scope) => Number(compiled.evaluate(scope)));
}
