package challenge

import (
	"reflect"
	"testing"
)

func TestWordFrequency(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want map[string]int
	}{
		{
			name: "simple repeats",
			in:   "the cat sat on the mat",
			want: map[string]int{"the": 2, "cat": 1, "sat": 1, "on": 1, "mat": 1},
		},
		{
			name: "punctuation and case",
			in:   "Hello, hello! HELLO.",
			want: map[string]int{"hello": 3},
		},
		{
			name: "interior apostrophe kept",
			in:   "don't stop don't",
			want: map[string]int{"don't": 2, "stop": 1},
		},
		{
			name: "tabs and newlines as whitespace",
			in:   "a\tb\nc a",
			want: map[string]int{"a": 2, "b": 1, "c": 1},
		},
		{
			name: "leading and trailing punctuation stripped",
			in:   "(go) [go]; {GO}",
			want: map[string]int{"go": 3},
		},
		{
			name: "digits are words",
			in:   "42 42 forty-two",
			want: map[string]int{"42": 2, "forty-two": 1},
		},
		{
			name: "token that is only punctuation is skipped",
			in:   "hi --- !!! bye",
			want: map[string]int{"hi": 1, "bye": 1},
		},
		{
			name: "empty input",
			in:   "",
			want: map[string]int{},
		},
		{
			name: "whitespace only",
			in:   "   \t \n  ",
			want: map[string]int{},
		},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := WordFrequency(c.in)
			if got == nil {
				t.Fatalf("WordFrequency(%q) returned nil map, want non-nil", c.in)
			}
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("WordFrequency(%q) = %v, want %v", c.in, got, c.want)
			}
		})
	}
}

func TestWordFrequencyEmptyIsNonNil(t *testing.T) {
	got := WordFrequency("")
	if got == nil {
		t.Fatal("WordFrequency(\"\") = nil, want non-nil empty map")
	}
	if len(got) != 0 {
		t.Errorf("WordFrequency(\"\") = %v, want empty map", got)
	}
}
