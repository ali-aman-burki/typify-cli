from typify_prototype.preprocessing.instance_utils import Instance

class MROBuilder:

	@staticmethod
	def build_mro(cls: Instance) -> list[Instance]:
		if cls in cls.origin.bases: return [cls]
		
		bases_mros = [base.origin.mro[:] for base in cls.origin.bases]
		bases_mros.append(cls.origin.bases[:])

		return [cls] + MROBuilder.c3_merge(bases_mros) 
	
	@staticmethod
	def c3_merge(seqs: list[list[Instance]]) -> list[Instance]:
		result = []
		while True:
			seqs = [s for s in seqs if s]
			if not seqs:
				return result
			for seq in seqs:
				candidate = seq[0]
				if all(candidate not in s[1:] for s in seqs):
					break
			else:
				raise TypeError("Inconsistent hierarchy, no C3 MRO possible")
			result.append(candidate)
			for seq in seqs:
				if seq[0] == candidate:
					seq.pop(0)

