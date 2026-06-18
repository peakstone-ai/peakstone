package challenge

import (
	"container/heap"
	"fmt"
)

// Job is a unit of work with dependencies and a scheduling priority.
type Job struct {
	ID       string
	Deps     []string
	Priority int
}

// Schedule returns a deterministic topological order of the jobs' IDs.
//
// Among jobs whose dependencies are all already scheduled (ready jobs), the one
// with the highest Priority is chosen next; ties are broken by the smallest ID.
//
// It returns an error if two jobs share an ID, if a dependency references an
// unknown ID, or if the dependencies contain a cycle.
func Schedule(jobs []Job) ([]string, error) {
	// Index jobs by ID, detecting duplicates.
	index := make(map[string]Job, len(jobs))
	for _, j := range jobs {
		if _, dup := index[j.ID]; dup {
			return nil, fmt.Errorf("duplicate job ID %q", j.ID)
		}
		index[j.ID] = j
	}

	// Validate dependencies and compute in-degrees over the deduped dep set.
	indegree := make(map[string]int, len(jobs))
	dependents := make(map[string][]string, len(jobs))
	for _, j := range jobs {
		if _, ok := indegree[j.ID]; !ok {
			indegree[j.ID] = 0
		}
		seen := make(map[string]bool, len(j.Deps))
		for _, dep := range j.Deps {
			if _, ok := index[dep]; !ok {
				return nil, fmt.Errorf("job %q depends on unknown ID %q", j.ID, dep)
			}
			if seen[dep] {
				continue // duplicate dep in the same job: count once
			}
			seen[dep] = true
			indegree[j.ID]++
			dependents[dep] = append(dependents[dep], j.ID)
		}
	}

	// Seed the ready heap with all zero-indegree jobs.
	ready := &readyHeap{}
	heap.Init(ready)
	for _, j := range jobs {
		if indegree[j.ID] == 0 {
			heap.Push(ready, readyJob{id: j.ID, priority: j.Priority})
		}
	}

	order := make([]string, 0, len(jobs))
	for ready.Len() > 0 {
		next := heap.Pop(ready).(readyJob)
		order = append(order, next.id)
		for _, dep := range dependents[next.id] {
			indegree[dep]--
			if indegree[dep] == 0 {
				heap.Push(ready, readyJob{id: dep, priority: index[dep].Priority})
			}
		}
	}

	if len(order) != len(jobs) {
		return nil, fmt.Errorf("cycle detected: %d of %d jobs cannot be scheduled", len(jobs)-len(order), len(jobs))
	}
	return order, nil
}

type readyJob struct {
	id       string
	priority int
}

// readyHeap orders by higher priority first, then smaller ID.
type readyHeap []readyJob

func (h readyHeap) Len() int { return len(h) }
func (h readyHeap) Less(i, j int) bool {
	if h[i].priority != h[j].priority {
		return h[i].priority > h[j].priority
	}
	return h[i].id < h[j].id
}
func (h readyHeap) Swap(i, j int) { h[i], h[j] = h[j], h[i] }
func (h *readyHeap) Push(x any)   { *h = append(*h, x.(readyJob)) }
func (h *readyHeap) Pop() any {
	old := *h
	n := len(old)
	item := old[n-1]
	*h = old[:n-1]
	return item
}
