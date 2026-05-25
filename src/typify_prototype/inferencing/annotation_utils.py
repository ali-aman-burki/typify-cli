import ast

from typing import Union
from dataclasses import (
	dataclass,
	field
)

from typify_prototype.inferencing.resolver import Resolver
from typify_prototype.inferencing.expression import PackedExpr
from typify_prototype.inferencing.commons import ParameterEntry
from typify_prototype.preprocessing.instance_utils import Instance

@dataclass(eq=False)
class Varnotation:
	annotation: Instance = None

@dataclass
class DeferredAnnotations:
	on: bool = False
	strings: set[str] = field(default_factory=set)
	holders: dict[Union[Union[Union[ParameterEntry, Instance], PackedExpr], Varnotation], str] = field(default_factory=dict)

	def compute(self, resolver: Resolver):
		lookup: dict[str, Instance] = {}

		for string in self.strings:
			node = ast.parse(string, mode='eval').body
			refset = resolver.resolve_value(node)
			
			if refset:
				ref = refset.ref()
				lookup[string] = ref.resolve_fully(resolver)
		
		for k, v in self.holders.items():
			from_lookup = lookup.get(v)
			if from_lookup:
				if isinstance(k, Instance): k.return_annotation = from_lookup
				elif isinstance(k, PackedExpr): k.base = from_lookup
				elif isinstance(k, ParameterEntry): k.annotation = from_lookup
				elif isinstance(k, Varnotation): k.annotation = from_lookup

class AnnotationUtils:
	
	@staticmethod
	def check_and_defer(
		deferred_annotations: DeferredAnnotations, 
		resolver: Resolver,
		node: ast.Expr, 
		obj: Union[Union[Union[Instance, PackedExpr], ParameterEntry], Varnotation],
	):
		from typify_prototype.inferencing.commons import Builtins

		string = ""
		if deferred_annotations.on:
			if isinstance(node, ast.Constant):
				if isinstance(node.value, str):
					string = node.value
					deferred_annotations.strings.add(string)
			else:
				string = ast.unparse(node)
				deferred_annotations.strings.add(string)
			
			deferred_annotations.holders[obj] = string
		else:
			refset = resolver.resolve_value(node)
			if refset:
				ref = refset.ref()
				if ref.instanceof(Builtins.get_type("str")):
					deferred_annotations.strings.add(ref.cval)
					deferred_annotations.holders[obj] = ref.cval
				else:
					if isinstance(obj, Instance):
						obj.return_annotation = ref
					elif isinstance(obj, PackedExpr):
						obj.base = ref
					elif isinstance(obj, ParameterEntry):
						obj.annotation = ref
					elif isinstance(obj, Varnotation):
						obj.annotation = ref

					strobjects = ref.collect_str_objects()
					strholders = ref.collect_str_holders()
					if strobjects:
						deferred_annotations.strings.update([o.cval for o in strobjects])
						deferred_annotations.holders.update(strholders)