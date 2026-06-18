# Dependency-aware job scheduler

Implement a file **`solution.go`** in `package challenge` exporting:

```go
type Job struct {
    ID       string
    Deps     []string
    Priority int
}

func Schedule(jobs []Job) ([]string, error)
```

`Schedule` computes a valid execution order for `jobs` and returns the slice of
job IDs in that order. The order is a **topological order**: a job may appear in
the output only after every ID in its `Deps` has already appeared earlier.

## Selection rule (deterministic)

Many topological orders may exist; this challenge fixes a single one. Build the
output by repeating the following step until every job is scheduled:

1. Consider the set of **ready** jobs: not-yet-scheduled jobs whose dependencies
   are *all* already scheduled.
2. Among the ready jobs, pick the one with the **highest `Priority`**.
3. Break ties (equal `Priority`) by the **lexicographically smallest `ID`**
   (Go string `<`).
4. Append the chosen job's ID to the output, mark it scheduled, and repeat.

This makes the result unique and fully determined by the input.

## Rules

- The output is a slice of job IDs (`[]string`). Every job appears exactly once.
- An **empty input** (`nil` or `len 0`) returns an empty (`len 0`) slice and a
  `nil` error.
- Return a non-nil error and a `nil`/empty slice when any of these hold:
  - **Duplicate ID** — two jobs share the same `ID`.
  - **Unknown dependency** — some job's `Deps` references an ID that is not the
    `ID` of any job in `jobs`.
  - **Cycle** — the dependencies form a cycle, so some jobs can never become
    ready. A self-dependency (`a` depends on `a`) is a cycle.
- Duplicate entries inside a single job's `Deps` are allowed and harmless: the
  dependency just needs to be satisfied once.

## Examples

Linear chain — `c` depends on `b`, `b` depends on `a`:

```go
Schedule([]Job{
    {ID: "c", Deps: []string{"b"}},
    {ID: "b", Deps: []string{"a"}},
    {ID: "a"},
})
// → ["a", "b", "c"], nil
```

Priority tie-break — `a` and `b` are both ready immediately; `b` has the higher
priority, so it runs first:

```go
Schedule([]Job{
    {ID: "a", Priority: 1},
    {ID: "b", Priority: 5},
})
// → ["b", "a"], nil
```

ID tie-break — equal priorities, so the smaller ID wins:

```go
Schedule([]Job{
    {ID: "y", Priority: 0},
    {ID: "x", Priority: 0},
})
// → ["x", "y"], nil
```

Diamond — `d` depends on both `b` and `c`, which both depend on `a`. With equal
priorities the smaller ID breaks the `b`/`c` tie:

```go
Schedule([]Job{
    {ID: "a"},
    {ID: "b", Deps: []string{"a"}},
    {ID: "c", Deps: []string{"a"}},
    {ID: "d", Deps: []string{"b", "c"}},
})
// → ["a", "b", "c", "d"], nil
```

Cycle — returns an error:

```go
Schedule([]Job{
    {ID: "a", Deps: []string{"b"}},
    {ID: "b", Deps: []string{"a"}},
})
// → nil, <error>
```

Use only the Go standard library.
