export type Row = Record<string, number | string>;

export class QueryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "QueryError";
  }
}

// ---------------------------------------------------------------------------
// AST
// ---------------------------------------------------------------------------

type CompareOp = "=" | "!=" | "<" | ">" | "<=" | ">=";

type Comparison = {
  kind: "cmp";
  col: string;
  op: CompareOp;
  value: number | string;
};

type Condition =
  | Comparison
  | { kind: "and"; left: Condition; right: Condition }
  | { kind: "or"; left: Condition; right: Condition };

type OrderBy = { col: string; dir: "asc" | "desc" };

type SelectStmt = {
  columns: "*" | string[];
  where: Condition | null;
  orderBy: OrderBy | null;
  limit: number | null;
};

// ---------------------------------------------------------------------------
// Tokenizer
// ---------------------------------------------------------------------------

type Token =
  | { type: "ident"; value: string }
  | { type: "string"; value: string }
  | { type: "number"; value: number }
  | { type: "op"; value: CompareOp }
  | { type: "comma" }
  | { type: "star" };

const IDENT_START = /[A-Za-z_]/;
const IDENT_PART = /[A-Za-z0-9_]/;
const DIGIT = /[0-9]/;

function tokenize(sql: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  const n = sql.length;

  while (i < n) {
    const ch = sql[i]!;

    if (ch === " " || ch === "\t" || ch === "\n" || ch === "\r") {
      i++;
      continue;
    }

    if (ch === ",") {
      tokens.push({ type: "comma" });
      i++;
      continue;
    }

    if (ch === "*") {
      tokens.push({ type: "star" });
      i++;
      continue;
    }

    // Operators: order matters so we match the two-char forms first.
    if (ch === "<" || ch === ">") {
      if (sql[i + 1] === "=") {
        tokens.push({ type: "op", value: ch === "<" ? "<=" : ">=" });
        i += 2;
      } else {
        tokens.push({ type: "op", value: ch === "<" ? "<" : ">" });
        i += 1;
      }
      continue;
    }
    if (ch === "=") {
      tokens.push({ type: "op", value: "=" });
      i++;
      continue;
    }
    if (ch === "!") {
      if (sql[i + 1] === "=") {
        tokens.push({ type: "op", value: "!=" });
        i += 2;
        continue;
      }
      throw new QueryError(`unexpected character '!' at position ${i}`);
    }

    // Single-quoted string literal.
    if (ch === "'") {
      let j = i + 1;
      let buf = "";
      let closed = false;
      while (j < n) {
        if (sql[j] === "'") {
          closed = true;
          break;
        }
        buf += sql[j];
        j++;
      }
      if (!closed) {
        throw new QueryError("unterminated string literal");
      }
      tokens.push({ type: "string", value: buf });
      i = j + 1;
      continue;
    }

    // Number literal (optionally signed). A leading '-' is only a number sign
    // when followed by a digit; otherwise it is an unexpected character.
    if (DIGIT.test(ch) || (ch === "-" && i + 1 < n && DIGIT.test(sql[i + 1]!))) {
      let j = ch === "-" ? i + 1 : i;
      while (j < n && DIGIT.test(sql[j]!)) j++;
      const text = sql.slice(i, j);
      const num = Number(text);
      if (!Number.isInteger(num)) {
        throw new QueryError(`invalid number literal '${text}'`);
      }
      tokens.push({ type: "number", value: num });
      i = j;
      continue;
    }

    // Identifier / keyword.
    if (IDENT_START.test(ch)) {
      let j = i;
      while (j < n && IDENT_PART.test(sql[j]!)) j++;
      tokens.push({ type: "ident", value: sql.slice(i, j) });
      i = j;
      continue;
    }

    throw new QueryError(`unexpected character '${ch}' at position ${i}`);
  }

  return tokens;
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------

class Parser {
  private pos = 0;
  constructor(private readonly tokens: Token[]) {}

  private peek(): Token | undefined {
    return this.tokens[this.pos];
  }

  private next(): Token {
    const t = this.tokens[this.pos];
    if (t === undefined) throw new QueryError("unexpected end of query");
    this.pos++;
    return t;
  }

  private atEnd(): boolean {
    return this.pos >= this.tokens.length;
  }

  /** Consume an identifier whose lowercased text equals `kw`. */
  private expectKeyword(kw: string): void {
    const t = this.peek();
    if (t === undefined || t.type !== "ident" || t.value.toLowerCase() !== kw) {
      throw new QueryError(`expected '${kw.toUpperCase()}'`);
    }
    this.pos++;
  }

  /** If the next token is the keyword `kw`, consume it and return true. */
  private matchKeyword(kw: string): boolean {
    const t = this.peek();
    if (t !== undefined && t.type === "ident" && t.value.toLowerCase() === kw) {
      this.pos++;
      return true;
    }
    return false;
  }

  private expectIdent(): string {
    const t = this.next();
    if (t.type !== "ident") throw new QueryError("expected an identifier");
    return t.value;
  }

  parse(): SelectStmt {
    this.expectKeyword("select");
    const columns = this.parseColumns();
    this.expectKeyword("from");
    // Table name: accepted but ignored.
    this.expectIdent();

    let where: Condition | null = null;
    if (this.matchKeyword("where")) {
      where = this.parseOr();
    }

    let orderBy: OrderBy | null = null;
    if (this.matchKeyword("order")) {
      this.expectKeyword("by");
      const col = this.expectIdent();
      let dir: "asc" | "desc" = "asc";
      if (this.matchKeyword("asc")) {
        dir = "asc";
      } else if (this.matchKeyword("desc")) {
        dir = "desc";
      }
      orderBy = { col, dir };
    }

    let limit: number | null = null;
    if (this.matchKeyword("limit")) {
      const t = this.next();
      if (t.type !== "number" || !Number.isInteger(t.value) || t.value < 0) {
        throw new QueryError("LIMIT expects a non-negative integer");
      }
      limit = t.value;
    }

    if (!this.atEnd()) {
      throw new QueryError("unexpected tokens after end of statement");
    }

    return { columns, where, orderBy, limit };
  }

  private parseColumns(): "*" | string[] {
    const first = this.peek();
    if (first !== undefined && first.type === "star") {
      this.pos++;
      return "*";
    }
    const cols: string[] = [];
    cols.push(this.expectIdent());
    while (this.peek()?.type === "comma") {
      this.pos++; // consume comma
      cols.push(this.expectIdent());
    }
    return cols;
  }

  // OR has the lowest precedence.
  private parseOr(): Condition {
    let left = this.parseAnd();
    while (this.matchKeyword("or")) {
      const right = this.parseAnd();
      left = { kind: "or", left, right };
    }
    return left;
  }

  // AND binds tighter than OR.
  private parseAnd(): Condition {
    let left = this.parseComparison();
    while (this.matchKeyword("and")) {
      const right = this.parseComparison();
      left = { kind: "and", left, right };
    }
    return left;
  }

  private parseComparison(): Comparison {
    const col = this.expectIdent();
    const opTok = this.next();
    if (opTok.type !== "op") throw new QueryError("expected a comparison operator");
    const valTok = this.next();
    if (valTok.type !== "number" && valTok.type !== "string") {
      throw new QueryError("expected an integer or string literal");
    }
    return { kind: "cmp", col, op: opTok.value, value: valTok.value };
  }
}

// ---------------------------------------------------------------------------
// Evaluation
// ---------------------------------------------------------------------------

function compare(cell: number | string | undefined, op: CompareOp, value: number | string): boolean {
  if (cell === undefined) {
    // Missing column: only `!=` is a "match".
    return op === "!=";
  }

  switch (op) {
    case "=":
      return cell === value;
    case "!=":
      return cell !== value;
    default: {
      // Ordering: only well-defined for matching types.
      if (typeof cell === "number" && typeof value === "number") {
        switch (op) {
          case "<":
            return cell < value;
          case ">":
            return cell > value;
          case "<=":
            return cell <= value;
          case ">=":
            return cell >= value;
        }
      }
      if (typeof cell === "string" && typeof value === "string") {
        switch (op) {
          case "<":
            return cell < value;
          case ">":
            return cell > value;
          case "<=":
            return cell <= value;
          case ">=":
            return cell >= value;
        }
      }
      // Type mismatch.
      return false;
    }
  }
}

function evalCondition(cond: Condition, row: Row): boolean {
  switch (cond.kind) {
    case "cmp":
      return compare(row[cond.col], cond.op, cond.value);
    case "and":
      return evalCondition(cond.left, row) && evalCondition(cond.right, row);
    case "or":
      return evalCondition(cond.left, row) || evalCondition(cond.right, row);
  }
}

function orderKeyCompare(a: number | string | undefined, b: number | string | undefined): number {
  // Both numbers -> numeric; both strings -> lexicographic; anything else -> equal.
  if (typeof a === "number" && typeof b === "number") {
    return a < b ? -1 : a > b ? 1 : 0;
  }
  if (typeof a === "string" && typeof b === "string") {
    return a < b ? -1 : a > b ? 1 : 0;
  }
  return 0;
}

function project(row: Row, columns: "*" | string[]): Row {
  if (columns === "*") {
    return { ...row };
  }
  const out: Row = {};
  for (const col of columns) {
    if (Object.prototype.hasOwnProperty.call(row, col)) {
      out[col] = row[col]!;
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function query(sql: string, rows: Row[]): Row[] {
  const stmt = new Parser(tokenize(sql)).parse();

  // WHERE
  let working: Row[] = stmt.where === null ? rows.slice() : rows.filter((r) => evalCondition(stmt.where!, r));

  // ORDER BY (stable)
  if (stmt.orderBy !== null) {
    const ob = stmt.orderBy;
    const decorated = working.map((row, index) => ({ row, index }));
    decorated.sort((x, y) => {
      const c = orderKeyCompare(x.row[ob.col], y.row[ob.col]);
      const dirAdjusted = ob.dir === "desc" ? -c : c;
      if (dirAdjusted !== 0) return dirAdjusted;
      return x.index - y.index; // stability
    });
    working = decorated.map((d) => d.row);
  }

  // LIMIT
  if (stmt.limit !== null) {
    working = working.slice(0, stmt.limit);
  }

  // Projection
  return working.map((row) => project(row, stmt.columns));
}
