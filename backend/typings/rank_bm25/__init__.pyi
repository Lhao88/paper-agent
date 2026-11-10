from numpy import float64
from numpy.typing import NDArray

class BM25Plus:
    def __init__(
        self, corpus: list[list[str]], *, k1: float = 1.5, b: float = 0.75, delta: float = 1.0
    ) -> None: ...
    def get_scores(self, query: list[str]) -> NDArray[float64]: ...
