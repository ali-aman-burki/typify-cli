from typify_prototype.preprocessing.instance_utils import ReferenceSet, Instance
from typify_prototype.inferencing.commons import ArgTuple

class CallSignature:
	def __init__(
		self, 
		fobject: Instance, 
		caller: Instance, 
		arguments: dict[str, ArgTuple], 
	):
		self.fobject = fobject
		self.caller = caller
		self.arguments = arguments
		self.returns = ReferenceSet()
		self.running = False

	def __eq__(self, other):
		if not isinstance(other, CallSignature): return NotImplemented
		if self.fobject != other.fobject: return False
		return True

	def __hash__(self):
		return hash(self.fobject)

	def __repr__(self):
		return self.fobject.origin.parent.fqn + "()"

class CallStack:
	def __init__(self):
		self.stack: list[CallSignature] = []

	def push(self, signature: CallSignature):
		self.stack.append(signature)

	def pop(self) -> CallSignature:
		popped = self.stack.pop()
		return popped

	def contains(self, signature: CallSignature):
		return signature in self.stack

	def get(self, signature: CallSignature):
		for sig in self.stack:
			if sig == signature:
				return sig
		return signature