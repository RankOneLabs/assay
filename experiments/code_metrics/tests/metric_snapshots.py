from __future__ import annotations

VIEWS = """from shop.store import audit, load


def get_view(item_id):
    item = load(item_id)
    if item is None:
        return {"status": 404}
    audit("get", item_id)
    return {"status": 200, "body": item}
"""
BEFORE = {
    "src/shop/__init__.py": "",
    "src/shop/store.py": "DATA = {}\n\n\ndef load(item_id):\n    return DATA.get(item_id)\n\n\n"
    "def audit(action, item_id):\n    print(action, item_id)\n",
    "src/shop/views.py": VIEWS,
    "src/shop/routes.py": "from shop.views import get_view\n\n\n"
    "def get_route(request):\n    return get_view(request['id'])\n",
    "README.md": "not measured\n",
}
DELEGATING = "\n\ndef close_route(request):\n    return get_view(request['id'])\n"
INLINED = """

def close_route(request):
    item_id = request["id"]
    item = load(item_id)
    if item is None:
        return {"status": 404}
    audit("close", item_id)
    for key in ("owner", "status"):
        if key not in item:
            return {"status": 500}
    return {"status": 200, "body": item}
"""


def _after(addition: str, imports: str = "") -> dict[str, str]:
    routes = BEFORE["src/shop/routes.py"]
    return {**BEFORE, "src/shop/routes.py": imports + routes + addition}




CASES = {
    "unchanged": (BEFORE, dict(BEFORE), {}),
    "delegating": (BEFORE, _after(DELEGATING), {}),
    "inlined": (
        BEFORE,
        _after(INLINED, "from shop.store import audit, load\n"),
        {"clone_min_lines": 3, "clone_min_tokens": 15},
    ),
    "first_python_file": ({}, {"module.py": "x = 1\n"}, {}),
    "last_python_file": ({"module.py": "x = 1\n"}, {"README.md": ""}, {}),
    "single_module": (
        {"module.py": "x = 1\n"},
        {"module.py": "import os\nx = 1\n"},
        {},
    ),
}

