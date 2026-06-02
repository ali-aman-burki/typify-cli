from .module_meta import ModuleMeta

class Sequencer:

	@staticmethod
	def _tarjan(graph: dict[ModuleMeta, list[ModuleMeta]]):
		index = 0
		indices: dict[ModuleMeta, int] = {}
		low_links: dict[ModuleMeta, int] = {}
		on_stack: set[ModuleMeta] = set()
		stack: list[ModuleMeta] = []
		result: list[list[ModuleMeta]] = []

		def strongconnect(node: ModuleMeta):
			nonlocal index
			indices[node] = index
			low_links[node] = index
			index += 1
			stack.append(node)
			on_stack.add(node)

			for neighbor in graph.get(node, []):
				if neighbor not in indices:
					strongconnect(neighbor)
					low_links[node] = min(low_links[node], low_links[neighbor])
				elif neighbor in on_stack:
					low_links[node] = min(low_links[node], indices[neighbor])

			if low_links[node] == indices[node]:
				scc: list[ModuleMeta] = []
				while True:
					popped_node = stack.pop()
					on_stack.remove(popped_node)
					scc.append(popped_node)
					if popped_node == node:
						break
				result.append(scc)

		for node in graph:
			if node not in indices:
				strongconnect(node)

		return result

	@staticmethod
	def generate_sequences(graph: dict[ModuleMeta, list[ModuleMeta]]) -> list[list[ModuleMeta]]:
		sequences: list[list[ModuleMeta]] = Sequencer._tarjan(graph)

		for seq in sequences:
			seq.reverse()

		return sequences
