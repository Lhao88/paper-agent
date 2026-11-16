from uuid import uuid4

from app.memory.library import EXCLUDED, INCLUDED, PINNED, admission_for, candidate_ids
from app.planning.admit import admit_actions
from tests.unit.test_admit import action, coverage, research_spec


def test_pinned_value_matches_admit_and_excluded_papers_leave_the_candidate_set() -> None:
    kept = uuid4()
    pinned = uuid4()
    excluded = uuid4()
    assert admission_for(PINNED).status == "pinned"
    assert admission_for(INCLUDED).included is True
    assert admission_for(EXCLUDED).status == "excluded"
    assert candidate_ids(
        [(kept, INCLUDED), (pinned, PINNED), (excluded, EXCLUDED)]
    ) == [kept, pinned]
    low = admission_for(PINNED)
    low.paper_id = pinned
    low.relevance = 2
    result = admit_actions(
        research_spec(),
        [
            action(
                "read_fulltext",
                action_id="pinned-read",
                paper_ids=[pinned],
                providers=[],
                query=None,
            )
        ],
        coverage(),
        [low],
        remaining_source_requests=5,
        remaining_llm_calls=5,
        remaining_deep_reads=5,
    )
    assert [item.action_id for item in result.actions] == ["pinned-read"]
