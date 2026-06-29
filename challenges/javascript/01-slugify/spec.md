# Slugify a title

Implement an ES module **`solution.js`** exporting a single function:

```js
export function slugify(input) { /* ... */ }
```

Convert a human title string into a URL slug:

- Lowercase the whole string.
- Treat **any character that is not an ASCII letter (`a–z`) or digit (`0–9`) as a separator** —
  this includes spaces, punctuation, underscores, and non-ASCII letters.
- Replace each **run** of one or more separators with a **single** hyphen (`-`).
- Strip any leading or trailing hyphens from the result.

Return the resulting slug (a string). An input made entirely of separators returns `""`.

Examples:
```js
slugify("Hello World")          // => "hello-world"
slugify("  Hello,  World!  ")   // => "hello-world"
slugify("already-clean")        // => "already-clean"
slugify("Top 10 Tips")          // => "top-10-tips"
slugify("a---b__c")             // => "a-b-c"
slugify("@#$%")                 // => ""
```
