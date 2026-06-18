package challenge

import (
	"reflect"
	"sync"
	"sync/atomic"
	"testing"
)

func TestMapConcurrentMatchesSequential(t *testing.T) {
	fn := func(x int) int { return x*x + 1 }
	cases := []struct {
		name    string
		inputs  []int
		workers int
	}{
		{"empty", []int{}, 4},
		{"nil", nil, 4},
		{"single", []int{7}, 1},
		{"single many workers", []int{7}, 16},
		{"workers one", []int{1, 2, 3, 4, 5}, 1},
		{"workers equal len", []int{1, 2, 3, 4}, 4},
		{"workers gt len", []int{1, 2, 3}, 10},
		{"larger", []int{9, 8, 7, 6, 5, 4, 3, 2, 1, 0, -1, -2}, 3},
		{"negatives", []int{-5, -4, -3, -2, -1}, 2},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			want := make([]int, len(c.inputs))
			for i, v := range c.inputs {
				want[i] = fn(v)
			}
			got := MapConcurrent(c.inputs, c.workers, fn)
			if len(got) != len(c.inputs) {
				t.Fatalf("len = %d, want %d", len(got), len(c.inputs))
			}
			if !reflect.DeepEqual(got, want) {
				t.Errorf("MapConcurrent(%v, %d) = %v, want %v", c.inputs, c.workers, got, want)
			}
		})
	}
}

func TestMapConcurrentOrderPreserved(t *testing.T) {
	// Identity maps input value to output position; any reordering would be caught.
	inputs := make([]int, 200)
	for i := range inputs {
		inputs[i] = i * 3
	}
	got := MapConcurrent(inputs, 7, func(x int) int { return x })
	for i, v := range inputs {
		if got[i] != v {
			t.Fatalf("index %d = %d, want %d (order not preserved)", i, got[i], v)
		}
	}
}

func TestMapConcurrentEmptyReturnsLenZero(t *testing.T) {
	got := MapConcurrent(nil, 4, func(x int) int { return x })
	if len(got) != 0 {
		t.Fatalf("len = %d, want 0", len(got))
	}
}

func TestMapConcurrentRespectsWorkerLimit(t *testing.T) {
	inputs := make([]int, 100)
	for i := range inputs {
		inputs[i] = i
	}
	const limit = 4

	var mu sync.Mutex
	cond := sync.NewCond(&mu)
	var active int64
	var maxActive int64
	var arrived int

	// fn blocks until either `limit` callers are concurrently in flight or no more
	// callers can arrive. This forces real concurrency while bounding it at `limit`:
	// if the implementation ran fewer than `limit` workers it would deadlock-stall,
	// and any run above `limit` would be recorded in maxActive.
	fn := func(x int) int {
		cur := atomic.AddInt64(&active, 1)
		for {
			m := atomic.LoadInt64(&maxActive)
			if cur <= m || atomic.CompareAndSwapInt64(&maxActive, m, cur) {
				break
			}
		}
		mu.Lock()
		arrived++
		if arrived >= limit {
			cond.Broadcast()
		}
		for arrived < limit {
			cond.Wait()
		}
		mu.Unlock()
		atomic.AddInt64(&active, -1)
		return x * 2
	}

	got := MapConcurrent(inputs, limit, fn)
	if m := atomic.LoadInt64(&maxActive); m > limit {
		t.Fatalf("observed %d concurrent workers, limit was %d", m, limit)
	}
	if atomic.LoadInt64(&maxActive) < 2 {
		t.Fatalf("no real concurrency observed (maxActive=%d)", maxActive)
	}
	for i := range inputs {
		if got[i] != inputs[i]*2 {
			t.Fatalf("index %d = %d, want %d", i, got[i], inputs[i]*2)
		}
	}
}

func TestMapConcurrentCallsFnOncePerElement(t *testing.T) {
	inputs := []int{10, 20, 30, 40, 50, 60}
	var calls int64
	got := MapConcurrent(inputs, 3, func(x int) int {
		atomic.AddInt64(&calls, 1)
		return x + 1
	})
	if calls != int64(len(inputs)) {
		t.Fatalf("fn called %d times, want %d", calls, len(inputs))
	}
	for i, v := range inputs {
		if got[i] != v+1 {
			t.Errorf("index %d = %d, want %d", i, got[i], v+1)
		}
	}
}
