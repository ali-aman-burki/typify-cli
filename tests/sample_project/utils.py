def add(a, b):
    return a + b


def greet(name):
    message = "Hello, " + name
    return message


def is_positive(n):
    return n > 0


def compute(x, y):
    total = x + y
    doubled = total * 2
    return doubled


def get_info():
    name = "Alice"
    age = 30
    score = 9.5
    active = True
    nothing = None
    return name, age, score, active, nothing


def process_items(items):
    count = len(items)
    result = []
    for item in items:
        result.append(item)
    return count


def make_mapping():
    d = {"key": "value", "count": 42}
    keys = list(d.keys())
    return d


PI = 3.14159
VERSION = "1.0.0"
MAX_RETRIES = 5
DEBUG = False


def circle_area(radius):
    area = PI * radius * radius
    return area
