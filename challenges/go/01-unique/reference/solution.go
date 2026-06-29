package challenge

// Unique returns the elements of xs with duplicates removed, preserving the
// order of first occurrence. The input is not modified and the result is
// always non-nil.
func Unique(xs []int) []int {
	seen := make(map[int]bool, len(xs))
	out := make([]int, 0, len(xs))
	for _, x := range xs {
		if !seen[x] {
			seen[x] = true
			out = append(out, x)
		}
	}
	return out
}
