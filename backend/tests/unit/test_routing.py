from app.workflow.routing import decide_route


def test_supplement_and_read_share_one_round():
    assert decide_route("retrieve_more", 1, 1, True) == "write"
    assert decide_route("read_more", 1, 1, True) == "write"
    assert decide_route("retrieve_more", 0, 1, False) == "write"
    assert decide_route("read_more", 0, 1, True) == "read"
    assert decide_route("retrieve_more", 0, 1, True) == "retrieve"
