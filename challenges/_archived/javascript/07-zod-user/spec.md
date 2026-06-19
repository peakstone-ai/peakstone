# Validate user (zod)

Implement an ES module **`solution.js`** that uses **zod** (already installed, **zod v4** —
import it) to validate a user object:

```js
import { z } from "zod";

export function validateUser(obj) { /* ... */ }
```

Build a zod schema for a user with exactly these fields:
- `name`: a non-empty string (`z.string().min(1)`)
- `age`: an integer `>= 0` (`z.number().int().min(0)`)
- `email`: a valid email address (`z.email()` in zod v4)

`validateUser` must call `schema.safeParse(obj)` and return:
- on success: `{ success: true, data }` where `data` is the parsed object
- on failure: `{ success: false, errors }` where `errors` is an **array of the issue
  message strings** (i.e. `result.error.issues.map((i) => i.message)`)

The function must not throw on invalid input — always return one of the two shapes above.

Examples:
```js
validateUser({ name: "Ada", age: 36, email: "ada@example.com" })
// => { success: true, data: { name: "Ada", age: 36, email: "ada@example.com" } }

validateUser({ name: "", age: -1, email: "nope" })
// => { success: false, errors: [ <message>, <message>, <message> ] }  // 3 issues
```
