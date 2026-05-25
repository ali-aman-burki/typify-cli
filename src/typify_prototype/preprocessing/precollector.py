import ast

from typing import Union
from typify_prototype.preprocessing.module_meta import ModuleMeta


class PreCollector(ast.NodeVisitor):

    @staticmethod
    def collect_parameter_slots(fdef: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> list[str]:
        args_node = fdef.args
        names: list[str] = []
        for arg in args_node.posonlyargs:
            names.append(arg.arg)
        for arg in args_node.args:
            names.append(arg.arg)
        for arg in args_node.kwonlyargs:
            names.append(arg.arg)
        if args_node.vararg:
            names.append(args_node.vararg.arg)
        if args_node.kwarg:
            names.append(args_node.kwarg.arg)
        return names

    @staticmethod
    def collect_targets(expr: ast.expr) -> dict[ast.expr, tuple[int, int]]:
        targets: dict[ast.expr, tuple[int, int]] = {}

        def visit(node: ast.expr):
            if isinstance(node, (ast.Name, ast.Attribute)):
                targets[node] = (node.lineno, node.col_offset)
            elif isinstance(node, (ast.Tuple, ast.List)):
                for elt in node.elts:
                    visit(elt)
            elif isinstance(node, ast.Starred):
                visit(node.value)

        visit(expr)
        return targets

    def __init__(self, module_meta: ModuleMeta, typeslots: bool):
        self.module_meta = module_meta
        self.typeslots = typeslots
        self.scope_stack: list[str] = []

    def _format_fqn(self) -> str:
        return ".".join(self.scope_stack)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        from typify_prototype.preprocessing.instance_utils import ReferenceSet, VSlot
        position = (node.target.lineno, node.target.col_offset)
        vslot = VSlot(
            scope=self._format_fqn(),
            name=ast.unparse(node.target),
            u_type=ReferenceSet(),
        )
        if self.typeslots:
            self.module_meta.register_vslot(position, vslot)
        self.module_meta.register_vslot_snapshot(position, vslot)

    def visit_AugAssign(self, node: ast.AugAssign):
        from typify_prototype.preprocessing.instance_utils import ReferenceSet, VSlot
        position = (node.target.lineno, node.target.col_offset)
        vslot = VSlot(
            scope=self._format_fqn(),
            name=ast.unparse(node.target),
            u_type=ReferenceSet(),
        )
        if self.typeslots:
            self.module_meta.register_vslot(position, vslot)
        self.module_meta.register_vslot_snapshot(position, vslot)

    def visit_Assign(self, node: ast.Assign):
        from typify_prototype.preprocessing.instance_utils import ReferenceSet, VSlot
        fqn = self._format_fqn()
        for bigtarget in node.targets:
            for target, position in PreCollector.collect_targets(bigtarget).items():
                vslot = VSlot(
                    scope=fqn,
                    name=ast.unparse(target),
                    u_type=ReferenceSet(),
                )
                if self.typeslots:
                    self.module_meta.register_vslot(position, vslot)
                self.module_meta.register_vslot_snapshot(position, vslot)

    def visit_ClassDef(self, node: ast.ClassDef):
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        from typify_prototype.preprocessing.instance_utils import ReferenceSet, FSlot
        fqn = self._format_fqn()
        position = (node.lineno, node.col_offset)
        param_names = PreCollector.collect_parameter_slots(node)
        fslot = FSlot(
            scope=fqn,
            name=node.name,
            u_params={k: ReferenceSet() for k in param_names},
            u_ret=ReferenceSet(),
        )
        if self.typeslots:
            self.module_meta.register_fslot(position, fslot)
        self.module_meta.register_fslot_snapshot(position, fslot)

        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)
