import os
import pathlib
import ast

class ANSIColors:
	RESET: str = "\033[0m"
	BLACK: str = "\033[30m"
	RED: str = "\033[31m"
	GREEN: str = "\033[32m"
	YELLOW: str = "\033[33m"
	BLUE: str = "\033[34m"
	MAGENTA: str = "\033[35m"
	CYAN: str = "\033[36m"
	WHITE: str = "\033[37m"
	GRAY: str = "\033[90m"

	BRIGHT_RED: str = "\033[91m"
	BRIGHT_GREEN: str = "\033[92m"
	BRIGHT_YELLOW: str = "\033[93m"
	BRIGHT_BLUE: str = "\033[94m"
	BRIGHT_MAGENTA: str = "\033[95m"
	BRIGHT_CYAN: str = "\033[96m"
	BRIGHT_WHITE: str = "\033[97m"

	@staticmethod
	def rgb(r: int, g: int, b: int) -> str:
		return f"\033[38;2;{r};{g};{b}m"

	@staticmethod
	def hex(hex_str: str) -> str:
		hex_str = hex_str.lstrip("#")
		if len(hex_str) != 6:
			raise ValueError("Hex color must be in format '#RRGGBB'")
		r = int(hex_str[0:2], 16)
		g = int(hex_str[2:4], 16)
		b = int(hex_str[4:6], 16)
		return ANSIColors.rgb(r, g, b)

class Utils:
	
	title = r"""
  _______             _  ___        
 |__   __|           (_)|  _|       
	| | _   _  _ __   _ | |_  _   _ 
	| || | | || '_ \ | ||  _|| | | |
	| || |_| || |_) || || |  | |_| |
	|_| \__, || .__/ |_||_|   \__, |
		 __/ || |              __/ |
		|___/ |_|             |___/ 
"""

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
	
	@staticmethod
	def pretty_list_arrow(data: list, columns: int):
		result = ""

		col_widths = []
		for col in range(columns):
			col_items = data[col::columns]
			if col_items:
				col_widths.append(max(len(str(item)) for item in col_items))
			else:
				col_widths.append(0)

		for i in range(0, len(data), columns):
			row = data[i:i + columns]
			formatted_parts = []
			for j, item in enumerate(row):
				if j == columns - 1:
					formatted_parts.append(f"➜ {str(item)}")
				else:
					formatted_parts.append(f"➜ {str(item):<{col_widths[j]}}")
			result += " ".join(formatted_parts) + "\n"

		return result

	@staticmethod
	def last_n_parts(path: pathlib.Path, n: int) -> str:
		parts = path.parts
		n = max(1, min(n, len(parts)))

		if len(parts) <= n:
			return str(path)
		else:
			truncated_path = pathlib.Path("...") / pathlib.Path(*parts[-n:])
			return truncated_path.as_posix()