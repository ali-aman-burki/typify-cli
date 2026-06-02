import sys
import warnings
from .utils import ANSIColors

class LogLevel:
    TRACE = 10
    DEBUG = 20
    INFO = 30
    WARNING = 40
    ERROR = 50
    OFF = 60

LEVEL_COLORS = {
    "TRACE": ANSIColors.CYAN,
    "DEBUG": ANSIColors.BLUE,
    "INFO": ANSIColors.GREEN,
    "WARNING": ANSIColors.BRIGHT_YELLOW,
    "ERROR": ANSIColors.BRIGHT_RED,
}

class Logger:
    def __init__(self, level: int = LogLevel.INFO):
        self.level = level
        self.outputs = []
        self._orig_showwarning = None
        self.emoji_map = {
			"ok": "🟢",     
			"changed": "🟡",
			"refresh": "🔵",
			"warn": "🟠",   
			"error": "🔴",  
			"skip": "⚪",   

			"search": "🔍",  
			"start": "🚀",  
			"init": "🔧",   
			"build": "🏗️",  
			"patch": "♻️",  
			"file": "📄",   
			"folder": "📁", 
			"summary": "📦",
			"types": "📝",  
			"libs": "📚",   
			"graph": "🕸️",  

            "push": "📥",
			"pop": "📤",
			"arrow_up": "⬆️",
			"arrow_down": "⬇️",
			"arrow_left": "⬅️",
			"arrow_right": "➡️",
			"arrow_loop": "🔄",  
			"arrow_branch": "↕️",
		}


    def set_level(self, level: int):
        self.level = level

    def add_output(self, stream):
        self.outputs.append(stream)

    def _emit(self, level_name: str, msg: str, severity: int, trail: int, header: bool):
        if severity < self.level:
            return

        prefix = f"[{level_name}] " if header else ""
        plain_msg = f"{prefix}{msg}"
        color = LEVEL_COLORS.get(level_name, ANSIColors.WHITE)
        color_msg = f"{color}{plain_msg}{ANSIColors.RESET}"

        for out in self.outputs:
            if out in (sys.stdout, sys.stderr):
                print("\n" * trail, end="", file=out)
                print(color_msg, file=out)
            else:
                out.write("\n" * trail + plain_msg + "\n")
                out.flush()

    def trace(self, msg: str, trail: int = 0, header: bool = True):
        self._emit("TRACE", msg, LogLevel.TRACE, trail, header)

    def debug(self, msg: str, trail: int = 0, header: bool = True):
        self._emit("DEBUG", msg, LogLevel.DEBUG, trail, header)

    def info(self, msg: str, trail: int = 0, header: bool = True):
        self._emit("INFO", msg, LogLevel.INFO, trail, header)

    def warning(self, msg: str, trail: int = 0, header: bool = True):
        self._emit("WARNING", msg, LogLevel.WARNING, trail, header)

    def warn(self, msg: str, trail: int = 0, header: bool = True):
        self.warning(msg, trail=trail, header=header)

    def error(self, msg: str, trail: int = 0, header: bool = True):
        self._emit("ERROR", msg, LogLevel.ERROR, trail, header)

    def capture_warnings(self, enable: bool = True, include_category: bool = True, include_location: bool = True):
        if enable and self._orig_showwarning is None:
            self._orig_showwarning = warnings.showwarning

            def _showwarning(message, category, filename, lineno, file=None, line=None):
                parts = ["(via Python warnings)"]
                if include_category and category:
                    parts.append(f"{category.__name__}:")
                parts.append(str(message).rstrip("\n"))
                if include_location and filename and lineno:
                    parts.append(f"[{filename}:{lineno}]")
                formatted = " ".join(parts)
                self.warning(formatted, header=True)

            warnings.showwarning = _showwarning
            warnings.simplefilter("default")

        elif not enable and self._orig_showwarning is not None:
            warnings.showwarning = self._orig_showwarning
            self._orig_showwarning = None

    def close(self):
        if self._orig_showwarning is not None:
            warnings.showwarning = self._orig_showwarning
            self._orig_showwarning = None

        for out in self.outputs:
            if out not in (sys.stdout, sys.stderr):
                try:
                    out.close()
                except Exception:
                    pass

logger = Logger(level=LogLevel.DEBUG) 
logger.capture_warnings(True)
