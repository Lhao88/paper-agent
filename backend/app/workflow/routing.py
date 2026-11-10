def decide_route(action: str, rounds: int, limit: int, has_new_material: bool) -> str:
    if rounds >= limit or not has_new_material:
        return "write"
    return {"retrieve_more": "retrieve", "read_more": "read"}.get(action, "write")
