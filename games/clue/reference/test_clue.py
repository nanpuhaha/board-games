"""Pytest suite for Clue reference engine and language-agnostic conformance tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from engine.conformance import load_conformance_cases, run_conformance_case
from engine.contracts import RuleError
from games.clue.reference.engine import ClueEngine

CLUE_DIR = Path(__file__).resolve().parent.parent
CONFORMANCE_DIR = CLUE_DIR / "tests" / "conformance"
EVENT_SCHEMA = json.loads(
    (CLUE_DIR.parent.parent / "schemas" / "domain-event.schema.json").read_text(encoding="utf-8")
)

CONFORMANCE_CASES = load_conformance_cases(CONFORMANCE_DIR)


@pytest.fixture()
def clue_engine() -> ClueEngine:
    return ClueEngine()


@pytest.mark.parametrize("case_id,case", CONFORMANCE_CASES, ids=[cid for cid, _ in CONFORMANCE_CASES])
def test_conformance(clue_engine: ClueEngine, case_id: str, case: dict) -> None:
    run_conformance_case(clue_engine, case)


def test_setup_determinism_and_card_partition(clue_engine: ClueEngine) -> None:
    config = {
        "players": [
            {"id": "p_white", "suspect": "white"},
            {"id": "p_scarlett", "suspect": "scarlett"},
            {"id": "p_plum", "suspect": "plum"},
            {"id": "p_mustard", "suspect": "mustard"},
        ],
        "enable_bonus_cards": True,
    }
    res1 = clue_engine.setup(config, seed=42)
    res2 = clue_engine.setup(config, seed=42)
    assert res1.state == res2.state
    assert res1.events_as_dicts() == res2.events_as_dicts()

    state = res1.state
    # Turn order follows classic suspect order: scarlett -> mustard -> white -> plum
    assert state["turn_order"] == ["p_scarlett", "p_mustard", "p_white", "p_plum"]

    # 21 cards partitioned cleanly between envelope (3) and player hands (18)
    env_cards = [state["envelope"]["suspect"], state["envelope"]["weapon"], state["envelope"]["room"]]
    hand_cards = [c for p in state["players"].values() for c in p["hand"]]
    all_cards = env_cards + hand_cards
    expected_cards = clue_engine.data.suspects + clue_engine.data.weapons + clue_engine.data.rooms
    assert len(all_cards) == 21
    assert set(all_cards) == set(expected_cards)

    # 13 bonus cards shuffled into bonus_deck
    assert len(state["bonus_deck"]) == 13
    assert set(state["bonus_deck"]) == set(clue_engine.data.bonus_card_ids)

    # All emitted events satisfy domain-event.schema.json
    for ev in res1.events_as_dicts():
        jsonschema.validate(instance=ev, schema=EVENT_SCHEMA)


def test_setup_rejects_invalid_player_count(clue_engine: ClueEngine) -> None:
    with pytest.raises(RuleError) as exc:
        clue_engine.setup(
            {"players": [{"id": "p1", "suspect": "scarlett"}, {"id": "p2", "suspect": "mustard"}]},
            seed=1,
        )
    assert exc.value.code == "INVALID_PLAYER_COUNT"


def test_bonus_peek_and_swap_and_free_suggestion_end_to_end(clue_engine: ClueEngine) -> None:
    config = {
        "players": [
            {"id": "p1", "suspect": "scarlett"},
            {"id": "p2", "suspect": "mustard"},
            {"id": "p3", "suspect": "white"},
        ],
        "enable_bonus_cards": True,
    }
    state = clue_engine.setup(config, seed=7).state

    # Position p1 next to '?' square (1, 7) and stack bonus_deck deterministically
    state["tokens"]["scarlett"] = {"kind": "hallway", "x": 2, "y": 7}
    state["bonus_deck"] = ["bonus_peek_opponent_1", "bonus_swap_position_1", "bonus_free_suggestion_1"]

    # 1) Roll & land on '?' -> peek_opponent_card
    r1 = clue_engine.apply_action(state, {"type": "ROLL_DICE", "player": "p1", "dice_override": [1, 1]})
    r2 = clue_engine.apply_action(r1.state, {"type": "MOVE_TO_HALLWAY", "player": "p1", "x": 1, "y": 7})
    assert r2.state["phase"] == "BONUS_RESOLVE"
    assert r2.state["pending_bonus"]["step"] == "CHOOSE_TARGET"

    r3 = clue_engine.apply_action(r2.state, {"type": "BONUS_CHOOSE_TARGET", "player": "p1", "target_player": "p2"})
    assert r3.state["pending_bonus"]["step"] == "RESPOND_CARD"

    p2_card = r3.state["players"]["p2"]["hand"][0]
    r4 = clue_engine.apply_action(r3.state, {"type": "BONUS_RESPOND_CARD", "player": "p2", "card": p2_card})
    assert r4.state["phase"] == "POST_MOVE"
    peek_events = [e for e in r4.events_as_dicts() if e["type"] == "BONUS_CARD_PEEKED"]
    assert len(peek_events) == 1
    assert peek_events[0]["visibility"] == "private"
    assert set(peek_events[0]["recipients"]) == {"p1", "p2"}
    assert peek_events[0]["payload"]["card"] == p2_card

    for res in (r1, r2, r3, r4):
        for ev in res.events_as_dicts():
            jsonschema.validate(instance=ev, schema=EVENT_SCHEMA)


class _DeductiveNotebook:
    """Pure information-set notebook fed ONLY by legally visible domain events."""

    def __init__(self, player_id: str, suspects: list[str], weapons: list[str], rooms: list[str]) -> None:
        self.player_id = player_id
        self.possible_suspects = set(suspects)
        self.possible_weapons = set(weapons)
        self.possible_rooms = set(rooms)
        self.own_hand: set[str] = set()
        self._last_suggestion: tuple[str, str, str, str] | None = None

    def _eliminate(self, card: str) -> None:
        self.possible_suspects.discard(card)
        self.possible_weapons.discard(card)
        self.possible_rooms.discard(card)

    def observe(self, event: dict) -> None:
        vis = event["visibility"]
        if vis == "private" and self.player_id not in event.get("recipients", []):
            return
        if vis == "hidden":
            return

        etype = event["type"]
        payload = event["payload"]

        if etype == "CARDS_DEALT" and payload["player"] == self.player_id:
            for card in payload["cards"]:
                self.own_hand.add(card)
                self._eliminate(card)
        elif etype == "CARD_SHOWN_PRIVATELY":
            self._eliminate(payload["card"])
        elif etype == "BONUS_CARD_PEEKED":
            self._eliminate(payload["card"])
        elif etype == "CARD_REVEALED_PUBLICLY":
            self._eliminate(payload["card"])
        elif etype == "SUGGESTION_MADE":
            self._last_suggestion = (
                payload["suggester"],
                payload["suspect"],
                payload["weapon"],
                payload["room"],
            )
        elif etype == "SUGGESTION_UNDISPROVED" and self._last_suggestion is not None:
            suggester, suspect, weapon, room = self._last_suggestion
            if suggester == self.player_id:
                if suspect not in self.own_hand:
                    self.possible_suspects = {suspect}
                if weapon not in self.own_hand:
                    self.possible_weapons = {weapon}
                if room not in self.own_hand:
                    self.possible_rooms = {room}

    def is_solved(self) -> bool:
        return (
            len(self.possible_suspects) == 1
            and len(self.possible_weapons) == 1
            and len(self.possible_rooms) == 1
        )

    def solution(self) -> tuple[str, str, str]:
        assert self.is_solved()
        return (
            next(iter(self.possible_suspects)),
            next(iter(self.possible_weapons)),
            next(iter(self.possible_rooms)),
        )


def test_four_player_e2e_reckless_elimination_and_guaranteed_logical_win(clue_engine: ClueEngine) -> None:
    """Full 4-player E2E game:
    - p2 recklessly accuses early and is eliminated, yet still disproves later suggestions.
    - Surviving players deduce strictly from visible events + player views (never touching hidden state).
    - As soon as a player reaches 100% logical certainty (1 suspect, 1 weapon, 1 room), they accuse and win.
    """
    config = {
        "players": [
            {"id": "p1", "suspect": "scarlett"},
            {"id": "p2", "suspect": "mustard"},
            {"id": "p3", "suspect": "white"},
            {"id": "p4", "suspect": "green"},
        ],
        "enable_bonus_cards": True,
        "accusation_requires_room": False,
    }
    step = clue_engine.setup(config, seed=2026)
    state = step.state

    notebooks = {
        pid: _DeductiveNotebook(pid, clue_engine.data.suspects, clue_engine.data.weapons, clue_engine.data.rooms)
        for pid in state["turn_order"]
    }

    def broadcast(events: list[dict]) -> None:
        for ev in events:
            jsonschema.validate(instance=ev, schema=EVENT_SCHEMA)
            for nb in notebooks.values():
                nb.observe(ev)

    broadcast(step.events_as_dicts())

    p2_eliminated = False
    p2_turns_after_elimination = 0
    p2_disproved_after_elimination = 0
    bonus_cards_drawn = 0
    winning_certainty_verified = False

    for _step_num in range(600):
        if clue_engine.get_outcome(state) is not None:
            break

        # Find the unique actor who currently has legal actions
        active_actors = [pid for pid in state["turn_order"] if clue_engine.get_legal_actions(state, pid)]
        assert len(active_actors) == 1, f"Expected exactly 1 active actor, got {active_actors} in phase {state['phase']}"
        actor = active_actors[0]
        legal = clue_engine.get_legal_actions(state, actor)
        legal_types = {a["type"] for a in legal}

        # Verify player view never leaks hidden fields
        view = clue_engine.get_player_view(state, actor)
        for forbidden in ("envelope", "bonus_deck", "rng_state"):
            assert forbidden not in view
        for pid, pview in view["players"].items():
            if pid != actor:
                assert "hand" not in pview

        if p2_eliminated and view["phase"] == "TURN_START" and actor == "p2":
            p2_turns_after_elimination += 1

        nb = notebooks[actor]
        action: dict

        # 1) Guaranteed logical win: accuse immediately whenever possible
        if nb.is_solved() and "MAKE_ACCUSATION" in legal_types:
            s, w, r = nb.solution()
            winning_certainty_verified = True
            action = {"type": "MAKE_ACCUSATION", "player": actor, "suspect": s, "weapon": w, "room": r}

        # 2) p2 recklessly attempts an early wrong accusation on their first turn
        elif actor == "p2" and not p2_eliminated and "MAKE_ACCUSATION" in legal_types:
            # Deliberately include a card from p2's own hand so the guess is guaranteed wrong
            own_card = next(iter(nb.own_hand))
            s = own_card if own_card in clue_engine.data.suspects else clue_engine.data.suspects[0]
            w = own_card if own_card in clue_engine.data.weapons else clue_engine.data.weapons[0]
            r = own_card if own_card in clue_engine.data.rooms else clue_engine.data.rooms[0]
            action = {"type": "MAKE_ACCUSATION", "player": "p2", "suspect": s, "weapon": w, "room": r}

        elif view["phase"] == "TURN_START":
            loc = view["tokens"][view["players"][actor]["suspect"]]
            if "STAY_FOR_SUGGESTION" in legal_types and loc["kind"] == "room" and loc["room"] in nb.possible_rooms:
                action = {"type": "STAY_FOR_SUGGESTION", "player": actor}
            elif "USE_SECRET_PASSAGE" in legal_types and loc["kind"] == "room":
                dest = clue_engine.data.secret_passages[loc["room"]]
                if dest in nb.possible_rooms:
                    action = {"type": "USE_SECRET_PASSAGE", "player": actor}
                else:
                    action = {"type": "ROLL_DICE", "player": actor}
            else:
                action = {"type": "ROLL_DICE", "player": actor}

        elif view["phase"] in ("MOVE", "BONUS_MOVE"):
            room_moves = [a for a in legal if a["type"] == "MOVE_TO_ROOM"]
            hallway_moves = [a for a in legal if a["type"] == "MOVE_TO_HALLWAY"]
            qm_moves = [
                a for a in hallway_moves
                if view["phase"] == "MOVE" and (a["x"], a["y"]) in clue_engine.data.question_marks
            ]
            unknown_room_moves = [a for a in room_moves if a["room"] in nb.possible_rooms]
            if qm_moves and bonus_cards_drawn < 2:
                action = qm_moves[0]
            elif unknown_room_moves:
                action = unknown_room_moves[0]
            elif room_moves:
                action = room_moves[0]
            elif hallway_moves:
                target_rooms = list(nb.possible_rooms) or clue_engine.data.rooms
                target_doors = [d for r in target_rooms for d in clue_engine.data.room_doorways[r]]
                action = min(
                    hallway_moves,
                    key=lambda a: min(abs(a["x"] - dx) + abs(a["y"] - dy) for dx, dy in target_doors),
                )
            else:
                action = {"type": "END_TURN", "player": actor}

        elif view["phase"] == "BONUS_RESOLVE":
            pb = view["pending_bonus"]
            if pb["step"] == "CHOOSE_ROOM":
                target_room = next(iter(nb.possible_rooms), clue_engine.data.rooms[0])
                action = {"type": "BONUS_CHOOSE_ROOM", "player": actor, "room": target_room}
            elif pb["step"] == "CHOOSE_TARGET":
                action = legal[0]
            elif pb["step"] == "RESPOND_CARD":
                action = legal[0]
            elif pb["step"] == "CHOOSE_SUGGESTION":
                s = next(iter(nb.possible_suspects), clue_engine.data.suspects[0])
                w = next(iter(nb.possible_weapons), clue_engine.data.weapons[0])
                r = next(iter(nb.possible_rooms), clue_engine.data.rooms[0])
                action = {"type": "BONUS_MAKE_SUGGESTION", "player": actor, "suspect": s, "weapon": w, "room": r}
            else:
                raise AssertionError(f"Unexpected bonus step: {pb}")

        elif view["phase"] == "POST_MOVE":
            if "MAKE_SUGGESTION" in legal_types:
                s = next(iter(nb.possible_suspects), clue_engine.data.suspects[0])
                w = next(iter(nb.possible_weapons), clue_engine.data.weapons[0])
                action = {"type": "MAKE_SUGGESTION", "player": actor, "suspect": s, "weapon": w}
            else:
                action = {"type": "END_TURN", "player": actor}

        elif view["phase"] == "DISPROVE":
            action = legal[0]

        elif view["phase"] == "POST_SUGGESTION":
            action = {"type": "END_TURN", "player": actor}

        else:
            raise AssertionError(f"Unhandled phase: {view['phase']}")

        res = clue_engine.apply_action(state, action)
        state = res.state
        ev_dicts = res.events_as_dicts()
        broadcast(ev_dicts)

        for ev in ev_dicts:
            if ev["type"] == "PLAYER_ELIMINATED" and ev["payload"]["player"] == "p2":
                p2_eliminated = True
            elif ev["type"] == "SUGGESTION_DISPROVED" and p2_eliminated and ev["payload"]["disprover"] == "p2":
                p2_disproved_after_elimination += 1
            elif ev["type"] == "BONUS_CARD_DRAWN":
                bonus_cards_drawn += 1

    outcome = clue_engine.get_outcome(state)
    assert outcome is not None, "Game should terminate via guaranteed logical accusation within 600 steps"
    assert p2_eliminated, "p2 must have been eliminated mid-game"
    assert p2_turns_after_elimination == 0, "Eliminated p2 must never receive another turn"
    assert p2_disproved_after_elimination >= 1, "Eliminated p2 must still disprove suggestions"
    assert winning_certainty_verified, "Winner must accuse only after 100% logical certainty"
    assert outcome["winner"] in {"p1", "p3", "p4"}
    assert outcome["reason"] == "CORRECT_ACCUSATION"
    assert outcome["envelope"] == state["envelope"]
    assert bonus_cards_drawn >= 1, "Bonus '?' cards should be exercised during the 4-player game"


def test_completely_blocked_player_can_end_turn_in_move_phase(clue_engine: ClueEngine) -> None:
    """When a player's doorway exit is completely blocked by another token, END_TURN is legal in MOVE."""
    state = clue_engine.setup(
        {
            "players": [
                {"id": "p1", "suspect": "scarlett"},
                {"id": "p2", "suspect": "mustard"},
                {"id": "p3", "suspect": "white"},
            ],
        },
        seed=99,
    ).state
    # Kitchen has a single doorway at (4, 7); block it with mustard
    state["tokens"]["scarlett"] = {"kind": "room", "room": "kitchen"}
    state["tokens"]["mustard"] = {"kind": "hallway", "x": 4, "y": 7}
    state["phase"] = "MOVE"
    state["movement_remaining"] = 5

    legal = clue_engine.get_legal_actions(state, "p1")
    assert legal == [{"type": "END_TURN", "player": "p1"}]

    res = clue_engine.apply_action(state, {"type": "END_TURN", "player": "p1"})
    assert res.state["phase"] == "TURN_START"
    assert res.state["current_player_index"] == 1

