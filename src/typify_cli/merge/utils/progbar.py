import sys
import time
import threading

from typing import Optional, Literal
from .utils import ANSIColors

class ProgressBar:
	def __init__(
		self,
		total: int,
		length: int = 24,
		fill: str = '━',
		empty: str = '━',
		prefix: str = '',
		suffix: str = '',
		left: str = '',
		right: str = '',
		decimals: int = 1,
		progress_format: Literal["percent", "counter", "none"] = "counter",
		prefix_width: int = 36,
	) -> None:
		self.total: int = total
		self.length: int = length
		self.fill: str = fill
		self.empty: str = empty
		self.prefix: str = prefix
		self.suffix: str = suffix
		self.left: str = left
		self.right: str = right
		self.decimals: int = decimals
		self.progress_format: Literal["percent", "counter", "none"] = progress_format
		self.prefix_width: Optional[int] = max(prefix_width or 0, len(prefix))
		self.iteration: int = 0
		self._last_line_len: int = 0

	def display(self) -> None:
		self.update(0)
	
	def refresh(self) -> None:
		self.update(self.iteration) 

	def update(self, iteration: Optional[int] = None) -> None:
		if iteration is not None:
			self.iteration = iteration
		else:
			self.iteration += 1

		filled_len: int = int(self.length * self.iteration // self.total) if self.total > 0 else 0
		bar = (
			f"{ANSIColors.BRIGHT_GREEN}{self.fill * filled_len}{ANSIColors.RESET}"
			f"{ANSIColors.GRAY}{self.empty * (self.length - filled_len)}{ANSIColors.RESET}"
		)

		if self.progress_format == "percent":
			frac = self.iteration / float(self.total) if float(self.total) > 0 else 0
			progress_info = f"[{100 * (frac):.{self.decimals}f}%]"
		elif self.progress_format == "counter":
			progress_info = f"[{self.iteration}/{self.total}]"
		else:
			progress_info = ""

		components: list[str] = []

		if self.prefix:
			prefix_str = self.prefix.ljust(self.prefix_width) if self.prefix_width else self.prefix
			components.append(prefix_str)

		components.append(f'{self.left}{bar}{self.right}')

		if progress_info:
			components.append(progress_info)

		if self.suffix:
			components.append(self.suffix)

		output_str = ' '.join(components)
		output_len = len(output_str)

		leftover = max(self._last_line_len - output_len, 0)

		print('\r' + output_str, end='', file=sys.stdout)

		if leftover > 0:
			print(' ' * leftover, end='', file=sys.stdout)
			print('\b' * leftover, end='', file=sys.stdout)

		sys.stdout.flush()

		self._last_line_len = output_len

		if self.iteration >= self.total:
			print(file=sys.stdout)

class IndeterminateProgressBar:
	def __init__(
		self,
		length: int = 24,
		block_len: int = 8,
		speed: float = 0.025,
		fill: str = '━',
		empty: str = '━',
		prefix: str = '',
		suffix: str = '',
		left: str = '',
		right: str = '',
		prefix_width: int = 50,
	) -> None:
		self.length: int = length
		self.block_len: int = block_len
		self.speed: float = speed
		self.fill: str = fill
		self.empty: str = empty
		self.prefix: str = prefix
		self.suffix: str = suffix
		self.left: str = left
		self.right: str = right
		self.prefix_width: Optional[int] = max(prefix_width or 0, len(prefix))
		self._running: bool = False
		self._done: bool = False
		self._last_line_len: int = 0
		self._thread: Optional[threading.Thread] = None

	def _animate(self):
		position = 0

		while self._running:
			bar = [f"{ANSIColors.GRAY}{self.empty}{ANSIColors.RESET}"] * self.length
			for i in range(self.block_len):
				idx = position + i
				if 0 <= idx < self.length:
					bar[idx] = f"{ANSIColors.BRIGHT_GREEN}{self.fill}{ANSIColors.RESET}"

			bar_str = ''.join(bar)
			components = []

			if self.prefix:
				prefix_str = self.prefix.ljust(self.prefix_width) if self.prefix_width else self.prefix
				components.append(prefix_str)

			components.append(f"{self.left}{bar_str}{self.right}")

			if self.suffix:
				components.append(self.suffix)

			output_str = ' '.join(components)
			output_len = len(output_str)
			leftover = max(self._last_line_len - output_len, 0)

			print('\r' + output_str, end='', file=sys.stdout)

			if leftover > 0:
				print(' ' * leftover, end='', file=sys.stdout)
				print('\b' * leftover, end='', file=sys.stdout)

			sys.stdout.flush()
			self._last_line_len = output_len

			position += 1
			if position >= self.length:
				position = -self.block_len

			time.sleep(self.speed)

		bar_str = f"{ANSIColors.BRIGHT_GREEN}{self.fill * self.length}{ANSIColors.RESET}"
		output_str = ' '.join(filter(None, [
			self.prefix.ljust(self.prefix_width) if self.prefix else '',
			f"{self.left}{bar_str}{self.right}",
			self.suffix
		]))

		print('\r' + output_str, end='', file=sys.stdout)
		print(file=sys.stdout)
		sys.stdout.flush()

	def start(self):
		self._running = True
		self._thread = threading.Thread(target=self._animate)
		self._thread.daemon = True
		self._thread.start()

	def stop(self):
		self._running = False
		if self._thread:
			self._thread.join()

	def done(self):
		self.stop()
		self._done = True

	def set_prefix(self, prefix: str):
		self.prefix = prefix
		self.prefix_width = max(self.prefix_width, len(prefix))

	def set_suffix(self, suffix: str):
		self.suffix = suffix