package challenge

import "testing"

func TestLRUBasicGetPut(t *testing.T) {
	c := NewLRUCache[string, int](2)
	if _, ok := c.Get("missing"); ok {
		t.Fatalf("Get on empty cache returned ok=true")
	}
	c.Put("a", 1)
	c.Put("b", 2)
	if v, ok := c.Get("a"); !ok || v != 1 {
		t.Fatalf("Get(a) = (%d, %v), want (1, true)", v, ok)
	}
	if v, ok := c.Get("b"); !ok || v != 2 {
		t.Fatalf("Get(b) = (%d, %v), want (2, true)", v, ok)
	}
	if c.Len() != 2 {
		t.Fatalf("Len = %d, want 2", c.Len())
	}
}

func TestLRUZeroValueOnMiss(t *testing.T) {
	c := NewLRUCache[int, string](2)
	if v, ok := c.Get(99); ok || v != "" {
		t.Fatalf("Get(miss) = (%q, %v), want (\"\", false)", v, ok)
	}
}

func TestLRUEvictsLeastRecentlyUsed(t *testing.T) {
	c := NewLRUCache[string, int](2)
	c.Put("a", 1)
	c.Put("b", 2)
	c.Put("c", 3) // capacity 2: "a" is LRU, evicted
	if _, ok := c.Get("a"); ok {
		t.Fatalf("expected a to be evicted")
	}
	if v, ok := c.Get("b"); !ok || v != 2 {
		t.Fatalf("Get(b) = (%d, %v), want (2, true)", v, ok)
	}
	if v, ok := c.Get("c"); !ok || v != 3 {
		t.Fatalf("Get(c) = (%d, %v), want (3, true)", v, ok)
	}
	if c.Len() != 2 {
		t.Fatalf("Len = %d, want 2", c.Len())
	}
}

func TestLRUGetCountsAsUse(t *testing.T) {
	c := NewLRUCache[string, int](2)
	c.Put("a", 1)
	c.Put("b", 2)
	if v, ok := c.Get("a"); !ok || v != 1 { // "a" now most-recently-used
		t.Fatalf("Get(a) = (%d, %v), want (1, true)", v, ok)
	}
	c.Put("c", 3) // "b" is LRU now, should be evicted
	if _, ok := c.Get("b"); ok {
		t.Fatalf("expected b to be evicted (Get should have refreshed a)")
	}
	if v, ok := c.Get("a"); !ok || v != 1 {
		t.Fatalf("Get(a) = (%d, %v), want (1, true)", v, ok)
	}
	if v, ok := c.Get("c"); !ok || v != 3 {
		t.Fatalf("Get(c) = (%d, %v), want (3, true)", v, ok)
	}
}

func TestLRUUpdateExistingKey(t *testing.T) {
	c := NewLRUCache[string, int](2)
	c.Put("a", 1)
	c.Put("b", 2)
	c.Put("a", 100) // update value, refresh a; no eviction
	if c.Len() != 2 {
		t.Fatalf("Len = %d, want 2 (update must not evict)", c.Len())
	}
	if v, ok := c.Get("a"); !ok || v != 100 {
		t.Fatalf("Get(a) = (%d, %v), want (100, true)", v, ok)
	}
	c.Put("c", 3) // "b" is LRU, evicted
	if _, ok := c.Get("b"); ok {
		t.Fatalf("expected b to be evicted after updating a then inserting c")
	}
}

func TestLRUUpdateRefreshesRecency(t *testing.T) {
	c := NewLRUCache[string, int](2)
	c.Put("a", 1)
	c.Put("b", 2)
	c.Put("a", 10) // refresh "a" via update => "b" becomes LRU
	c.Put("c", 3)  // evicts "b"
	if _, ok := c.Get("b"); ok {
		t.Fatalf("expected b to be evicted; updating a should refresh its recency")
	}
	if v, ok := c.Get("a"); !ok || v != 10 {
		t.Fatalf("Get(a) = (%d, %v), want (10, true)", v, ok)
	}
}

func TestLRUCapacityOne(t *testing.T) {
	c := NewLRUCache[int, int](1)
	c.Put(1, 10)
	c.Put(2, 20) // evicts 1
	if _, ok := c.Get(1); ok {
		t.Fatalf("expected key 1 evicted in capacity-1 cache")
	}
	if v, ok := c.Get(2); !ok || v != 20 {
		t.Fatalf("Get(2) = (%d, %v), want (20, true)", v, ok)
	}
	if c.Len() != 1 {
		t.Fatalf("Len = %d, want 1", c.Len())
	}
}

func TestLRUZeroCapacity(t *testing.T) {
	c := NewLRUCache[string, int](0)
	c.Put("a", 1)
	if _, ok := c.Get("a"); ok {
		t.Fatalf("zero-capacity cache must store nothing")
	}
	if c.Len() != 0 {
		t.Fatalf("Len = %d, want 0", c.Len())
	}
}

func TestLRUStringValues(t *testing.T) {
	c := NewLRUCache[int, string](3)
	c.Put(1, "one")
	c.Put(2, "two")
	c.Put(3, "three")
	c.Get(1) // refresh 1
	c.Put(4, "four") // evicts 2 (LRU)
	if _, ok := c.Get(2); ok {
		t.Fatalf("expected key 2 evicted")
	}
	for _, want := range []struct {
		k int
		v string
	}{{1, "one"}, {3, "three"}, {4, "four"}} {
		if v, ok := c.Get(want.k); !ok || v != want.v {
			t.Errorf("Get(%d) = (%q, %v), want (%q, true)", want.k, v, ok, want.v)
		}
	}
}

func TestLRUEvictionChain(t *testing.T) {
	c := NewLRUCache[int, int](3)
	for i := 0; i < 6; i++ {
		c.Put(i, i*i)
	}
	// Only the last 3 inserts survive: 3,4,5.
	for _, k := range []int{0, 1, 2} {
		if _, ok := c.Get(k); ok {
			t.Errorf("expected key %d evicted", k)
		}
	}
	for _, k := range []int{3, 4, 5} {
		if v, ok := c.Get(k); !ok || v != k*k {
			t.Errorf("Get(%d) = (%d, %v), want (%d, true)", k, v, ok, k*k)
		}
	}
	if c.Len() != 3 {
		t.Fatalf("Len = %d, want 3", c.Len())
	}
}
