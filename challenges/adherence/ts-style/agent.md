# AGENTS.md — TypeScript project conventions (MANDATORY)

1. **No `any`.** Never use the `any` type (no `: any`, `as any`, `Array<any>`, etc.).
2. **`const` only.** Declare bindings with `const`. Never use `let` or `var`.
3. **Explicit return types.** Every exported function declares its return type.
4. **No `console`.** Never call `console.log` (or any `console.*`).
