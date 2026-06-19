import { test } from "node:test";
import { strict as assert } from "node:assert";
import { parseUser, UserSchema, type User } from "./solution.ts";

test("valid input returns a typed object", () => {
  const u: User = parseUser({ name: "Ada", age: 36, roles: ["admin", "user"] });
  assert.deepEqual(u, { name: "Ada", age: 36, roles: ["admin", "user"] });
});

test("empty roles array is allowed", () => {
  const u = parseUser({ name: "Bob", age: 0, roles: [] });
  assert.deepEqual(u, { name: "Bob", age: 0, roles: [] });
});

test("inferred type fields are usable at runtime", () => {
  const u = parseUser({ name: "Cy", age: 7, roles: ["user"] });
  assert.equal(u.name.toUpperCase(), "CY");
  assert.equal(u.age + 1, 8);
  assert.equal(u.roles.length, 1);
});

test("empty name throws", () => {
  assert.throws(() => parseUser({ name: "", age: 1, roles: ["user"] }));
});

test("negative age throws", () => {
  assert.throws(() => parseUser({ name: "Dot", age: -1, roles: ["user"] }));
});

test("non-integer age throws", () => {
  assert.throws(() => parseUser({ name: "Eve", age: 1.5, roles: ["user"] }));
});

test("unknown role throws", () => {
  assert.throws(() => parseUser({ name: "Fox", age: 2, roles: ["root"] }));
});

test("missing field and wrong type throw", () => {
  assert.throws(() => parseUser({ name: "Gus", roles: ["user"] }));
  assert.throws(() => parseUser("not an object"));
});

test("schema is reusable via safeParse", () => {
  assert.equal(UserSchema.safeParse({ name: "Hal", age: 9, roles: ["admin"] }).success, true);
  assert.equal(UserSchema.safeParse({ name: "", age: 9, roles: [] }).success, false);
});
