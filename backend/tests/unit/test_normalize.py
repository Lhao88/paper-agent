import pytest

from app.sources.normalize import normalize_doi, rebuild_abstract


def test_original_abstract_uses_reported_positions_and_missing_is_not_fabricated() -> None:
    assert rebuild_abstract({"study": [1], "We": [0], "graphs": [2]}) == "We study graphs"
    assert rebuild_abstract(None) is None


def test_conflicting_abstract_positions_are_rejected() -> None:
    with pytest.raises(ValueError):
        rebuild_abstract({"first": [0], "different": [0]})


@pytest.mark.parametrize(
    "raw, expected",
    [
        (" https://doi.org/10.1234/ABC ", "10.1234/abc"),
        ("DOI:10.1234/ABC", "10.1234/abc"),
        (None, None),
        ("not-a-doi", None),
    ],
)
def test_doi_identity_is_normalized_without_inventing_identifiers(raw, expected) -> None:
    assert normalize_doi(raw) == expected
