package challenge

import "testing"

func TestHasCycle(t *testing.T) {
	cases := []struct {
		name  string
		graph map[string][]string
		want  bool
	}{
		{
			name:  "nil graph",
			graph: nil,
			want:  false,
		},
		{
			name:  "empty graph",
			graph: map[string][]string{},
			want:  false,
		},
		{
			name:  "single node no edges",
			graph: map[string][]string{"a": {}},
			want:  false,
		},
		{
			name:  "simple DAG",
			graph: map[string][]string{"a": {"b"}, "b": {"c"}, "c": {}},
			want:  false,
		},
		{
			name: "diamond DAG (shared descendant, no cycle)",
			graph: map[string][]string{
				"a": {"b", "c"},
				"b": {"d"},
				"c": {"d"},
				"d": {},
			},
			want: false,
		},
		{
			name:  "self-loop",
			graph: map[string][]string{"a": {"a"}},
			want:  true,
		},
		{
			name:  "two node cycle",
			graph: map[string][]string{"a": {"b"}, "b": {"a"}},
			want:  true,
		},
		{
			name:  "three node cycle",
			graph: map[string][]string{"a": {"b"}, "b": {"c"}, "c": {"a"}},
			want:  true,
		},
		{
			name: "cycle reachable only from one component",
			graph: map[string][]string{
				"x": {"y"},
				"y": {},
				"a": {"b"},
				"b": {"c"},
				"c": {"b"},
			},
			want: true,
		},
		{
			name: "neighbor not a key (implicit leaf), no cycle",
			graph: map[string][]string{
				"a": {"b"},
				"b": {"c"}, // c is not a key
			},
			want: false,
		},
		{
			name: "duplicate edges, no cycle",
			graph: map[string][]string{
				"a": {"b", "b", "b"},
				"b": {},
			},
			want: false,
		},
		{
			name: "duplicate edges forming cycle",
			graph: map[string][]string{
				"a": {"b", "b"},
				"b": {"a", "a"},
			},
			want: true,
		},
		{
			name: "long chain no cycle",
			graph: map[string][]string{
				"a": {"b"}, "b": {"c"}, "c": {"d"}, "d": {"e"}, "e": {"f"}, "f": {},
			},
			want: false,
		},
		{
			name: "cycle deep in chain",
			graph: map[string][]string{
				"a": {"b"}, "b": {"c"}, "c": {"d"}, "d": {"e"}, "e": {"c"},
			},
			want: true,
		},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := HasCycle(c.graph); got != c.want {
				t.Errorf("HasCycle(%v) = %v, want %v", c.graph, got, c.want)
			}
		})
	}
}
