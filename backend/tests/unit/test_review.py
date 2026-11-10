from uuid import uuid4

import pytest

from app.errors import DomainError
from app.review.models import SynthesisOutput
from app.review.validate import validate_synthesis


def test_analysis_cannot_introduce_unknown_question_or_evidence():
    evidence_id = uuid4()
    output = SynthesisOutput.model_validate(
        {
            "questions": [
                {
                    "question_id": "q9",
                    "findings": "unknown",
                    "evidence_ids": [str(evidence_id)],
                    "agreements": [],
                    "disagreements": [],
                    "gaps": [],
                }
            ],
            "outline": [
                {
                    "section_id": "s1",
                    "title": "methods",
                    "goal": "compare",
                    "question_ids": ["q9"],
                    "evidence_ids": [str(evidence_id)],
                }
            ],
        }
    )
    with pytest.raises(DomainError) as invalid:
        validate_synthesis(output, {"q1"}, {evidence_id})
    assert invalid.value.code == "SYNTHESIS_INVALID"
    with pytest.raises(DomainError):
        validate_synthesis(output, {"q9"}, set())
