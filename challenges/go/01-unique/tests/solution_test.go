package challenge

import (
	"reflect"
	"testing"
)

func TestUnique(t *testing.T) {
	cases := []struct {
		name string
		in   []int
		want []int
	}{
		{"removes duplicates preserving order", []int{3, 1, 3, 2, 1}, []int{3, 1, 2}},
		{"already unique unchanged", []int{1, 2, 3}, []int{1, 2, 3}},
		{"all same collapses to one", []int{5, 5, 5}, []int{5}},
		{"empty returns empty", []int{}, []int{}},
		{"single element", []int{42}, []int{42}},
		{"negatives and zero", []int{0, -1, 0, -1, 2}, []int{0, -1, 2}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := Unique(tc.in)
			if !reflect.DeepEqual(got, tc.want) {
				t.Errorf("Unique(%v) = %v, want %v", tc.in, got, tc.want)
			}
		})
	}
}

func TestUniqueReturnsNonNil(t *testing.T) {
	if Unique([]int{}) == nil {
		t.Error("Unique should return a non-nil slice for empty input")
	}
	if Unique(nil) == nil {
		t.Error("Unique should return a non-nil slice for nil input")
	}
}

func TestUniqueDoesNotMutateInput(t *testing.T) {
	in := []int{1, 1, 2}
	_ = Unique(in)
	if !reflect.DeepEqual(in, []int{1, 1, 2}) {
		t.Errorf("input was mutated: got %v", in)
	}
}
