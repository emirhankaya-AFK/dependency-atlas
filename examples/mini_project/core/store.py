import json

def fetch(value):
    return json.loads(json.dumps(value))
