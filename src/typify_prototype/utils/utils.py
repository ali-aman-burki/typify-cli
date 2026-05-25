import os
import pathlib
import ast


class Utils:

    @staticmethod
    def load_tree(path: pathlib.Path):
        with open(path, "r", encoding="utf-8", errors="ignore") as file:
            src_code = file.read()
        try:
            return ast.parse(src_code)
        except SyntaxError:
            return ast.Module(body=[], type_ignores=[])

    @staticmethod
    def is_valid_directory(path):
        if os.path.exists(path) and os.path.isdir(path):
            return path
