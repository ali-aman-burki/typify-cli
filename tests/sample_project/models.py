class Counter:
    def __init__(self):
        self.count = 0
        self.name = "counter"
        self.active = True

    def increment(self):
        self.count = self.count + 1
        return self.count

    def reset(self):
        self.count = 0

    def get_name(self):
        return self.name

    def is_active(self):
        return self.active


class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def distance_from_origin(self):
        return (self.x ** 2 + self.y ** 2) ** 0.5

    def to_tuple(self):
        return (self.x, self.y)

    def __repr__(self):
        label = "Point"
        return label


def make_counter():
    c = Counter()
    return c


def build_list():
    items = [1, 2, 3, 4, 5]
    first = items[0]
    length = len(items)
    joined = ", ".join(str(i) for i in items)
    return items


def string_ops():
    s = "hello world"
    upper = s.upper()
    parts = s.split(" ")
    stripped = s.strip()
    length = len(s)
    return upper


def numeric_ops():
    x = 10
    y = 3
    quotient = x / y
    floordiv = x // y
    remainder = x % y
    power = x ** y
    negative = -x
    return quotient


def boolean_logic():
    a = True
    b = False
    both = a and b
    either = a or b
    negated = not a
    return both


def conditional(flag):
    if flag:
        result = "yes"
    else:
        result = "no"
    return result
