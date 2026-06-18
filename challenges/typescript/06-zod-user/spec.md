# Typed user validation (zod)

Implement **`solution.ts`** using **zod** (already installed, **zod v4** — import it as
`import { z } from "zod";`) to validate a user object and expose a precise inferred type.

Export exactly three things:

```ts
import { z } from "zod";

export const UserSchema = /* ... */;
export type User = z.infer<typeof UserSchema>;
export function parseUser(input: unknown): User;
```

Build `UserSchema` as a zod object with exactly these fields:

- `name`: a **non-empty** string (`z.string().min(1)`)
- `age`: an **integer** that is `>= 0` (`z.number().int().min(0)`)
- `roles`: an **array** whose elements are the literal union `"admin" | "user"`
  (e.g. `z.array(z.enum(["admin", "user"]))`)

`parseUser(input)`:
- takes `unknown`,
- calls `UserSchema.parse(input)` (the **throwing** variant),
- returns the parsed value typed as `User`.

On invalid input `parseUser` must **throw** (let `schema.parse` throw its `ZodError`).
`User` must be the inferred type — do not hand-write it.

Examples:
```ts
parseUser({ name: "Ada", age: 36, roles: ["admin", "user"] });
// => { name: "Ada", age: 36, roles: ["admin", "user"] }

parseUser({ name: "", age: -1, roles: ["root"] }); // throws
```

Keep it fully typed (must pass `tsc --noEmit` in strict mode). Do not use `any` in the
public API.
