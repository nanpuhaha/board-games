"""Common contracts for Python reference board game engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Visibility = Literal["public", "private", "hidden"]
GameState = dict[str, Any]
Action = dict[str, Any]
PlayerView = dict[str, Any]
Outcome = dict[str, Any]


class RuleError(Exception):
    """Raised when an action violates game rules."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message or code
        super().__init__(f"{self.code}: {self.message}")


@dataclass(frozen=True)
class DomainEvent:
    """Structured domain event emitted during setup or action application."""

    type: str
    visibility: Visibility
    payload: dict[str, Any] = field(default_factory=dict)
    recipients: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": self.type,
            "visibility": self.visibility,
            "payload": self.payload,
        }
        if self.visibility == "private":
            result["recipients"] = list(self.recipients)
        return result


@dataclass(frozen=True)
class StepResult:
    """Result of setup() or apply_action()."""

    state: GameState
    events: tuple[DomainEvent, ...] = ()

    def events_as_dicts(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.events]


class GameEngine(Protocol):
    """Standard language-agnostic engine contract implemented in Python."""

    def setup(self, config: dict[str, Any], seed: int) -> StepResult: ...

    def get_legal_actions(self, state: GameState, player_id: str) -> list[Action]: ...

    def apply_action(self, state: GameState, action: Action) -> StepResult: ...

    def get_player_view(self, state: GameState, player_id: str) -> PlayerView: ...

    def get_outcome(self, state: GameState) -> Outcome | None: ...
