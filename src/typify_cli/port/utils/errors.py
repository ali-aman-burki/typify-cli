import ast

from .logging import logger

def safeguard(default_factory, phase: str):
    def deco(fn):
        def wrapper(self, *args, **kwargs):
            try:
                return fn(self, *args, **kwargs)
            except Exception as e:
                node = None
                if args and isinstance(args[0], ast.AST):
                    node = args[0]
                loc = f"{getattr(node, 'lineno', '?')}:{getattr(node, 'col_offset', '?')}" if node else "?:?"
                tb = ""
                frag = ""
                try:
                    if node:
                        frag = " node=" + ast.dump(node, include_attributes=False)
                except Exception:
                    pass
                logger.error(f"[{phase}] {type(self).__name__}.{fn.__name__} at {loc}: {e}{frag}{tb}")
                return default_factory()
        return wrapper
    return deco