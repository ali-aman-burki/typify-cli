class Any: ...
class TypeVar: ...

class TypeVarTuple: ...
class NoReturn: ...
class NewType: ...

_T = TypeVar('_T')
_K = TypeVar('_K')
_V = TypeVar('_V')
_Ts = TypeVarTuple('_Ts')

class _GenericAlias: ...
class _UnpackGenericAlias: ...
class _UnionGenericAlias: ...
	
class Unpack: 

	@classmethod
	def __class_getitem__(cls, item) -> _UnpackGenericAlias: ...

class Generic: 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...

class Optional(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _UnionGenericAlias: ...
	
class Union(Generic[Unpack[_Ts]]): 

	@classmethod
	def __class_getitem__(cls, item) -> _UnionGenericAlias: ...
	
class Literal(Generic[Unpack[_Ts]]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class Annotated(Generic[_T, Unpack[_Ts]]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class Final(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class ClassVar(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...

class List(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class Set(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class Dict(Generic[_K, _V]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class Tuple(Generic[Unpack[_Ts]]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class FrozenSet(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class DefaultDict(Generic[_K, _V]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class Counter(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class ChainMap(Generic[_K, _V]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class Deque(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	

class Type(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class Generator(Generic[_T, _V, _K]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class AsyncGenerator(Generic[_T, _V]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class Coroutine(Generic[_T, _V, _K]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class Awaitable(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class AsyncIterable(Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	
class AsyncIterator(AsyncIterable[_T], Generic[_T]): 

	@classmethod
	def __class_getitem__(cls, item) -> _GenericAlias: ...
	