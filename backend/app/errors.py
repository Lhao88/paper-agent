from dataclasses import dataclass, field


@dataclass
class DomainError(Exception):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message
