from ...preprocessing.symbol_table import ClassDefinition
from .model import (
    GenericTree, 
    GenericConstruct
)	
class GenericPrinter:

	@staticmethod
	def pretty_print_gentree(
		tree: dict[ClassDefinition, GenericTree], 
		indent: int = 0
	):
		
		def indent_str(level):
			return "  " * level

		for clsdef, gentree in tree.items():
			if not gentree.subs and not gentree.gentree:
				continue

			print(f"{indent_str(indent)}Class: {clsdef.parent.id}")

			if gentree.subs:
				print(f"{indent_str(indent + 1)}Subs:")
				for inst_from, inst_to in gentree.subs.items():
					if isinstance(inst_to, list):
						targets = ", ".join(repr(t) for t in inst_to)
						print(f"{indent_str(indent + 2)}{repr(inst_from)} -> [{targets}]")
					else:
						print(f"{indent_str(indent + 2)}{repr(inst_from)} -> {repr(inst_to)}")

			if gentree.gentree:
				print(f"{indent_str(indent + 1)}gentree:")
				GenericPrinter.pretty_print_gentree(gentree.gentree, indent + 2)
	
	@staticmethod
	def pretty_print_genconstruct(
		flat: dict[ClassDefinition, GenericConstruct], 
		indent: int = 0
	):
		
		def indent_str(level: int) -> str:
			return "  " * level

		for clsdef, construct in flat.items():
			if not construct.subs and not construct.concsubs:
				continue

			print(f"{indent_str(indent)}Class: {clsdef.parent.id}")
			
			if construct.subs:
				print(f"{indent_str(indent + 1)}Subs:")
				for k, v in construct.subs.items():
					if isinstance(v, list):
						vals = ", ".join(repr(x) for x in v)
						print(f"{indent_str(indent + 2)}{repr(k)} -> [{vals}]")
					else:
						print(f"{indent_str(indent + 2)}{repr(k)} -> {repr(v)}")

			if construct.concsubs:
				print(f"{indent_str(indent + 1)}Concrete Subs:")
				for k, v in construct.concsubs.items():
					if isinstance(v, list):
						vals = ", ".join(str(x) if x is not None else "None" for x in v)
						print(f"{indent_str(indent + 2)}{repr(k)} -> [{vals}]")
					else:
						val_str = str(v) if v is not None else "None"
						print(f"{indent_str(indent + 2)}{repr(k)} -> {val_str}")