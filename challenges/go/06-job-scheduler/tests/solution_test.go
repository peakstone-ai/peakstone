package challenge

import (
	"reflect"
	"testing"
)

func TestScheduleEmpty(t *testing.T) {
	got, err := Schedule(nil)
	if err != nil {
		t.Fatalf("Schedule(nil) error = %v, want nil", err)
	}
	if len(got) != 0 {
		t.Fatalf("Schedule(nil) = %v, want empty slice", got)
	}

	got, err = Schedule([]Job{})
	if err != nil {
		t.Fatalf("Schedule([]) error = %v, want nil", err)
	}
	if len(got) != 0 {
		t.Fatalf("Schedule([]) = %v, want empty slice", got)
	}
}

func TestScheduleSingle(t *testing.T) {
	got, err := Schedule([]Job{{ID: "only"}})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if want := []string{"only"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("Schedule = %v, want %v", got, want)
	}
}

func TestScheduleLinearChain(t *testing.T) {
	jobs := []Job{
		{ID: "c", Deps: []string{"b"}},
		{ID: "b", Deps: []string{"a"}},
		{ID: "a"},
	}
	got, err := Schedule(jobs)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if want := []string{"a", "b", "c"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("Schedule = %v, want %v", got, want)
	}
}

func TestScheduleDiamond(t *testing.T) {
	jobs := []Job{
		{ID: "d", Deps: []string{"b", "c"}},
		{ID: "b", Deps: []string{"a"}},
		{ID: "c", Deps: []string{"a"}},
		{ID: "a"},
	}
	got, err := Schedule(jobs)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Equal priorities: a first, then b<c by ID, then d.
	if want := []string{"a", "b", "c", "d"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("Schedule = %v, want %v", got, want)
	}
}

func TestSchedulePriorityTieBreak(t *testing.T) {
	jobs := []Job{
		{ID: "a", Priority: 1},
		{ID: "b", Priority: 5},
		{ID: "c", Priority: 3},
	}
	got, err := Schedule(jobs)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// All ready; ordered by descending priority: b(5), c(3), a(1).
	if want := []string{"b", "c", "a"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("Schedule = %v, want %v", got, want)
	}
}

func TestScheduleSmallestIDTieBreak(t *testing.T) {
	jobs := []Job{
		{ID: "y", Priority: 0},
		{ID: "x", Priority: 0},
		{ID: "z", Priority: 0},
	}
	got, err := Schedule(jobs)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Equal priorities: lexicographic by ID.
	if want := []string{"x", "y", "z"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("Schedule = %v, want %v", got, want)
	}
}

func TestSchedulePriorityBeatsID(t *testing.T) {
	// "z" has higher priority than "a", so it must come first even though
	// "a" is the smaller ID.
	jobs := []Job{
		{ID: "a", Priority: 1},
		{ID: "z", Priority: 9},
	}
	got, err := Schedule(jobs)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if want := []string{"z", "a"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("Schedule = %v, want %v", got, want)
	}
}

func TestScheduleIndependentJobs(t *testing.T) {
	jobs := []Job{
		{ID: "b"},
		{ID: "a"},
		{ID: "d"},
		{ID: "c"},
	}
	got, err := Schedule(jobs)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// No deps, all priority 0: pure lexicographic order.
	if want := []string{"a", "b", "c", "d"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("Schedule = %v, want %v", got, want)
	}
}

func TestSchedulePriorityRespectsDependencies(t *testing.T) {
	// "low" has lower priority but is the only dependency-free job, so it
	// must run before the high-priority job that depends on it.
	jobs := []Job{
		{ID: "high", Deps: []string{"low"}, Priority: 100},
		{ID: "low", Priority: 1},
	}
	got, err := Schedule(jobs)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if want := []string{"low", "high"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("Schedule = %v, want %v", got, want)
	}
}

func TestScheduleComplexDeterministic(t *testing.T) {
	jobs := []Job{
		{ID: "build", Deps: []string{"compile"}, Priority: 5},
		{ID: "compile", Deps: []string{"fetch"}, Priority: 5},
		{ID: "fetch", Priority: 5},
		{ID: "lint", Deps: []string{"fetch"}, Priority: 10},
		{ID: "test", Deps: []string{"build", "lint"}, Priority: 1},
		{ID: "docs", Deps: []string{"fetch"}, Priority: 10},
	}
	got, err := Schedule(jobs)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// fetch first (only ready). Then ready={compile(5), lint(10), docs(10)}.
	// docs and lint tie at 10 -> docs < lint by ID. Then lint. Then compile.
	// After compile -> build ready. build(5). Then test.
	want := []string{"fetch", "docs", "lint", "compile", "build", "test"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("Schedule = %v, want %v", got, want)
	}
}

func TestScheduleDuplicateDepsIgnored(t *testing.T) {
	jobs := []Job{
		{ID: "b", Deps: []string{"a", "a", "a"}},
		{ID: "a"},
	}
	got, err := Schedule(jobs)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if want := []string{"a", "b"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("Schedule = %v, want %v", got, want)
	}
}

func TestScheduleCycleError(t *testing.T) {
	jobs := []Job{
		{ID: "a", Deps: []string{"b"}},
		{ID: "b", Deps: []string{"a"}},
	}
	got, err := Schedule(jobs)
	if err == nil {
		t.Fatalf("expected error for cycle, got order %v", got)
	}
	if len(got) != 0 {
		t.Fatalf("on cycle error, want empty slice, got %v", got)
	}
}

func TestScheduleLongerCycleError(t *testing.T) {
	jobs := []Job{
		{ID: "x"}, // schedulable
		{ID: "a", Deps: []string{"c"}},
		{ID: "b", Deps: []string{"a"}},
		{ID: "c", Deps: []string{"b"}},
	}
	got, err := Schedule(jobs)
	if err == nil {
		t.Fatalf("expected error for 3-node cycle, got order %v", got)
	}
	if len(got) != 0 {
		t.Fatalf("on cycle error, want empty slice, got %v", got)
	}
}

func TestScheduleSelfDependencyError(t *testing.T) {
	jobs := []Job{
		{ID: "a", Deps: []string{"a"}},
	}
	got, err := Schedule(jobs)
	if err == nil {
		t.Fatalf("expected error for self-dependency, got order %v", got)
	}
	if len(got) != 0 {
		t.Fatalf("on self-dependency error, want empty slice, got %v", got)
	}
}

func TestScheduleUnknownDepError(t *testing.T) {
	jobs := []Job{
		{ID: "a", Deps: []string{"ghost"}},
	}
	got, err := Schedule(jobs)
	if err == nil {
		t.Fatalf("expected error for unknown dep, got order %v", got)
	}
	if len(got) != 0 {
		t.Fatalf("on unknown-dep error, want empty slice, got %v", got)
	}
}

func TestScheduleDuplicateIDError(t *testing.T) {
	jobs := []Job{
		{ID: "a"},
		{ID: "a"},
	}
	got, err := Schedule(jobs)
	if err == nil {
		t.Fatalf("expected error for duplicate ID, got order %v", got)
	}
	if len(got) != 0 {
		t.Fatalf("on duplicate-ID error, want empty slice, got %v", got)
	}
}

func TestScheduleOutputIsValidTopoOrder(t *testing.T) {
	jobs := []Job{
		{ID: "a"},
		{ID: "b", Deps: []string{"a"}},
		{ID: "c", Deps: []string{"a"}},
		{ID: "d", Deps: []string{"b", "c"}},
		{ID: "e", Deps: []string{"d"}},
	}
	got, err := Schedule(jobs)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != len(jobs) {
		t.Fatalf("got %d ids, want %d", len(got), len(jobs))
	}
	pos := make(map[string]int, len(got))
	for i, id := range got {
		if _, dup := pos[id]; dup {
			t.Fatalf("id %q appears more than once in %v", id, got)
		}
		pos[id] = i
	}
	for _, j := range jobs {
		for _, dep := range j.Deps {
			if pos[dep] >= pos[j.ID] {
				t.Fatalf("dependency %q (pos %d) not before %q (pos %d) in %v",
					dep, pos[dep], j.ID, pos[j.ID], got)
			}
		}
	}
}
