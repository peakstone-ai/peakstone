import networkx as nx


def longest_dependency_chain(deps: dict[str, list[str]]) -> int:
    g = nx.DiGraph()
    for node, prereqs in deps.items():
        g.add_node(node)
        for p in prereqs:
            # edge prereq -> node (prereq comes before node)
            g.add_edge(p, node)
    if g.number_of_nodes() == 0:
        return 0
    path = nx.dag_longest_path(g)
    return len(path)
