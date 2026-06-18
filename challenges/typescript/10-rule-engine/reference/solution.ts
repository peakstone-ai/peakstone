export type Rule =
  | { op: "and"; rules: Rule[] }
  | { op: "or"; rules: Rule[] }
  | { op: "not"; rule: Rule }
  | { op: "eq" | "ne" | "lt" | "lte" | "gt" | "gte"; field: string; value: number | string }
  | { op: "in"; field: string; values: Array<number | string> };

export class RuleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RuleError";
  }
}

const COMPARE_OPS = new Set(["eq", "ne", "lt", "lte", "gt", "gte"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function order(
  op: "lt" | "lte" | "gt" | "gte",
  fieldValue: unknown,
  value: number | string,
): boolean {
  // Only compare when both sides share the same comparable type.
  if (typeof fieldValue === "number" && typeof value === "number") {
    switch (op) {
      case "lt":
        return fieldValue < value;
      case "lte":
        return fieldValue <= value;
      case "gt":
        return fieldValue > value;
      case "gte":
        return fieldValue >= value;
    }
  }
  if (typeof fieldValue === "string" && typeof value === "string") {
    switch (op) {
      case "lt":
        return fieldValue < value;
      case "lte":
        return fieldValue <= value;
      case "gt":
        return fieldValue > value;
      case "gte":
        return fieldValue >= value;
    }
  }
  return false;
}

export function evaluate(rule: Rule, record: Record<string, unknown>): boolean {
  if (!isRecord(rule)) {
    throw new RuleError("rule must be an object");
  }

  const node = rule as Record<string, unknown>;
  const op = node["op"];

  if (typeof op !== "string") {
    throw new RuleError("rule is missing a string `op`");
  }

  if (op === "and" || op === "or") {
    const rules = node["rules"];
    if (!Array.isArray(rules)) {
      throw new RuleError(`\`${op}\` requires an array \`rules\``);
    }
    if (op === "and") {
      return rules.every((sub) => evaluate(sub as Rule, record));
    }
    return rules.some((sub) => evaluate(sub as Rule, record));
  }

  if (op === "not") {
    const child = node["rule"];
    if (!isRecord(child)) {
      throw new RuleError("`not` requires a child `rule` object");
    }
    return !evaluate(child as Rule, record);
  }

  if (op === "in") {
    const field = node["field"];
    const values = node["values"];
    if (typeof field !== "string") {
      throw new RuleError("`in` requires a string `field`");
    }
    if (!Array.isArray(values)) {
      throw new RuleError("`in` requires an array `values`");
    }
    const fieldValue = record[field];
    return values.some((candidate) => candidate === fieldValue);
  }

  if (COMPARE_OPS.has(op)) {
    const field = node["field"];
    const value = node["value"];
    if (typeof field !== "string") {
      throw new RuleError(`\`${op}\` requires a string \`field\``);
    }
    if (typeof value !== "number" && typeof value !== "string") {
      throw new RuleError(`\`${op}\` requires a number or string \`value\``);
    }
    const fieldValue = record[field];
    switch (op) {
      case "eq":
        return fieldValue === value;
      case "ne":
        return fieldValue !== value;
      default:
        return order(op as "lt" | "lte" | "gt" | "gte", fieldValue, value);
    }
  }

  throw new RuleError(`unknown op: ${op}`);
}

export function filter(
  rule: Rule,
  records: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  return records.filter((record) => evaluate(rule, record));
}
