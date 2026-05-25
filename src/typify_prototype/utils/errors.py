def safeguard(default_factory, phase: str):
    def deco(fn):
        def wrapper(self, *args, **kwargs):
            try:
                return fn(self, *args, **kwargs)
            except Exception:
                return default_factory()
        return wrapper
    return deco
