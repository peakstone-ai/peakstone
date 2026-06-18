# Self-repair: query-string parser

The workspace has a buggy ES-module `solution.js` exporting `parseQuery(qs)`. It should parse a
URL query string into an object:

- `parseQuery("a=1&b=2")` → `{ a: "1", b: "2" }`
- a leading `"?"` is stripped: `parseQuery("?a=1")` → `{ a: "1" }`
- repeated keys collect into an array (in order): `parseQuery("x=1&x=2&x=3")` → `{ x: ["1","2","3"] }`
- values are URL-decoded: `parseQuery("name=John%20Doe")` → `{ name: "John Doe" }`
- a key with no `=` maps to `""`: `parseQuery("flag")` → `{ flag: "" }`
- `parseQuery("")` → `{}`

The current version mishandles most of these. Run the tests, fix `solution.js`, and re-run
until all pass.
