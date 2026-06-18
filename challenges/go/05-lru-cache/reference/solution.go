package challenge

import "container/list"

// LRUCache is a fixed-capacity least-recently-used cache.
type LRUCache[K comparable, V any] struct {
	capacity int
	ll       *list.List // front = most recently used
	items    map[K]*list.Element
}

type entry[K comparable, V any] struct {
	key   K
	value V
}

// NewLRUCache returns an empty cache holding at most `capacity` entries.
func NewLRUCache[K comparable, V any](capacity int) *LRUCache[K, V] {
	if capacity < 0 {
		capacity = 0
	}
	return &LRUCache[K, V]{
		capacity: capacity,
		ll:       list.New(),
		items:    make(map[K]*list.Element),
	}
}

// Get returns the value for key and whether it was present, marking it as used.
func (c *LRUCache[K, V]) Get(key K) (V, bool) {
	if el, ok := c.items[key]; ok {
		c.ll.MoveToFront(el)
		return el.Value.(*entry[K, V]).value, true
	}
	var zero V
	return zero, false
}

// Put inserts or updates key, evicting the least-recently-used entry if needed.
func (c *LRUCache[K, V]) Put(key K, value V) {
	if c.capacity == 0 {
		return
	}
	if el, ok := c.items[key]; ok {
		el.Value.(*entry[K, V]).value = value
		c.ll.MoveToFront(el)
		return
	}
	if c.ll.Len() >= c.capacity {
		back := c.ll.Back()
		if back != nil {
			c.ll.Remove(back)
			delete(c.items, back.Value.(*entry[K, V]).key)
		}
	}
	c.items[key] = c.ll.PushFront(&entry[K, V]{key: key, value: value})
}

// Len returns the number of stored entries.
func (c *LRUCache[K, V]) Len() int {
	return c.ll.Len()
}
