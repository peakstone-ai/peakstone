# Business days between (date-fns)

Implement an ES module **`solution.js`** that uses **date-fns** (already installed — import it):

```js
import { parseISO, eachDayOfInterval, isWeekend } from "date-fns";

export function businessDaysBetween(startISO, endISO) { /* ... */ }
```

Given two ISO date strings (`"YYYY-MM-DD"`), count the number of **business days**
(weekdays Monday–Friday) in the range **(start, end]** — that is, **exclusive of the
start date and inclusive of the end date**.

Rules:
- Saturday and Sunday are not business days.
- The start date itself is never counted (even if it is a weekday).
- The end date is counted if it is a weekday.
- If `end <= start`, return `0`.

Use date-fns helpers such as `parseISO`, `eachDayOfInterval`, and `isWeekend`.

Examples:
```js
businessDaysBetween("2024-01-01", "2024-01-05") // => 4
// Mon..Fri: start Mon excluded; Tue, Wed, Thu, Fri counted

businessDaysBetween("2024-01-05", "2024-01-08") // => 1
// Fri..Mon: Fri excluded, Sat/Sun weekend, Mon counted

businessDaysBetween("2024-01-01", "2024-01-01") // => 0
// same day

businessDaysBetween("2024-01-01", "2024-01-08") // => 5
// one week: Mon excluded; Tue–Fri (4) + next Mon (1)
```
