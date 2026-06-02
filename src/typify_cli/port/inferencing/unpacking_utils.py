from __future__ import annotations
from typing import Union
from dataclasses import dataclass

from ..preprocessing.symbol_table import (
	Name,
	NameDefinition,
)

@dataclass(frozen=True)
class TargetEntry:
	definition: NameDefinition
	namespace_name: Name
	symbol_name: Name = None

@dataclass
class PackGroup:
	groups: list[Union[set[TargetEntry], PackGroup]]
	starred: bool