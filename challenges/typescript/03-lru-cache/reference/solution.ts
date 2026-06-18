export class LRUCache<K, V> {
  private readonly capacity: number;
  // Map preserves insertion order; we treat the last entry as most-recently used.
  private readonly map = new Map<K, V>();

  constructor(capacity: number) {
    if (capacity < 1) throw new RangeError("capacity must be >= 1");
    this.capacity = capacity;
  }

  get(key: K): V | undefined {
    if (!this.map.has(key)) return undefined;
    const value = this.map.get(key) as V;
    // re-insert to mark as most-recently used
    this.map.delete(key);
    this.map.set(key, value);
    return value;
  }

  put(key: K, value: V): void {
    if (this.map.has(key)) {
      this.map.delete(key);
    } else if (this.map.size >= this.capacity) {
      const lru = this.map.keys().next().value as K;
      this.map.delete(lru);
    }
    this.map.set(key, value);
  }

  get size(): number {
    return this.map.size;
  }
}
