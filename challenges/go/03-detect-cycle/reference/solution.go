package challenge

// HasCycle reports whether the directed graph (given as an adjacency map)
// contains any cycle, including self-loops.
func HasCycle(graph map[string][]string) bool {
	const (
		white = 0 // unvisited
		gray  = 1 // on the current DFS stack
		black = 2 // fully explored
	)
	color := make(map[string]int)

	var dfs func(node string) bool
	dfs = func(node string) bool {
		color[node] = gray
		for _, next := range graph[node] {
			switch color[next] {
			case gray:
				return true
			case white:
				if dfs(next) {
					return true
				}
			}
		}
		color[node] = black
		return false
	}

	for node := range graph {
		if color[node] == white {
			if dfs(node) {
				return true
			}
		}
	}
	return false
}
