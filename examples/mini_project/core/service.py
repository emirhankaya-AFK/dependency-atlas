from .store import fetch
from .api import handle  # intentional cycle for demonstrations

def process(value):
    return fetch(value)
