from collections import deque


def shortest_path_len(graph: dict[str, list[str]], start: str, goal: str) -> int:
    if start == goal:
        return 0
    visited = {start}
    queue = deque([(start, 0)])
    while queue:
        node, dist = queue.popleft()
        for nbr in graph.get(node, []):
            if nbr == goal:
                return dist + 1
            if nbr not in visited:
                visited.add(nbr)
                queue.append((nbr, dist + 1))
    return -1
