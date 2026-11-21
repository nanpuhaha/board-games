"""Pytest suite for Splendor reference engine, conformance tests, and 4-player E2E simulation."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from engine.conformance import load_conformance_cases, run_conformance_case
from engine.contracts import RuleError
from games.splendor.reference.engine import SplendorEngine

SPLENDOR_DIR = Path(__file__).resolve().parent.parent
CONFORMANCE_DIR = SPLENDOR_DIR / "tests" / "conformance"
EVENT_SCHEMA = json.loads(
    (SPLENDOR_DIR.parent.parent / "schemas" / "domain-event.schema.json").read_text(encoding="utf-8")
)

CONFORMANCE_CASES = load_conformance_cases(CONFORMANCE_DIR)


@pytest.fixture()
def splendor_engine() -> SplendorEngine:
    return SplendorEngine()


@pytest.mark.parametrize("case_id,case", CONFORMANCE_CASES, ids=[cid for cid, _ in CONFORMANCE_CASES])
def test_conformance(splendor_engine: SplendorEngine, case_id: str, case: dict) -> None:
    run_conformance_case(splendor_engine, case)


@pytest.mark.parametrize(
    "player_count,expected_gems,expected_nobles",
    [(2, 4, 3), (3, 5, 4), (4, 7, 5)],
)
def test_setup_supply_and_card_partition(
    splendor_engine: SplendorEngine, player_count: int, expected_gems: int, expected_nobles: int
) -> None:
    players = [f"p{i+1}" for i in range(player_count)]
    r1 = splendor_engine.setup({"players": players}, seed=101)
    r2 = splendor_engine.setup({"players": players}, seed=101)
    assert r1.state == r2.state
    assert r1.events_as_dicts() == r2.events_as_dicts()

    state = r1.state
    for g in splendor_engine.data.gems:
        assert state["bank"][g] == expected_gems
    assert state["bank"]["gold"] == 5
    assert len(state["nobles"]) == expected_nobles

    all_cards = (
        [c for tier in ("1", "2", "3") for c in state["market"][tier]]
        + [c for tier in ("1", "2", "3") for c in state["decks"][tier]]
    )
    assert len(all_cards) == 90
    assert set(all_cards) == set(splendor_engine.data.cards.keys())

    for ev in r1.events_as_dicts():
        jsonschema.validate(instance=ev, schema=EVENT_SCHEMA)


def test_setup_rejects_invalid_player_count(splendor_engine: SplendorEngine) -> None:
    with pytest.raises(RuleError) as exc:
        splendor_engine.setup({"players": ["p1"]}, seed=1)
    assert exc.value.code == "INVALID_PLAYER_COUNT"


def test_four_player_splendor_e2e_with_invariants(splendor_engine: SplendorEngine) -> None:
    """Run a full 4-player Splendor game to completion while verifying conservation & visibility invariants."""
    step = splendor_engine.setup({"players": ["p1", "p2", "p3", "p4"], "target_points": 15}, seed=2026)
    state = step.state

    for ev in step.events_as_dicts():
        jsonschema.validate(instance=ev, schema=EVENT_SCHEMA)

    nobles_visited = 0
    reservations_made = 0
    discards_made = 0

    for _ in range(400):
        if splendor_engine.get_outcome(state) is not None:
            break

        actor = state["turn_order"][state["current_player_index"]]
        legal = splendor_engine.get_legal_actions(state, actor)
        assert legal, f"No legal actions for {actor} in phase {state['phase']}"

        # Verify player view hides decks and masks other players' blind reserves
        view = splendor_engine.get_player_view(state, actor)
        assert "decks" not in view
        for pid, pview in view["players"].items():
            if pid != actor:
                for res in pview["reserved"]:
                    if res["face_down"]:
                        assert "card_id" not in res and res["hidden"] is True

        pstate = view["players"][actor]
        phase = view["phase"]

        if phase == "DISCARD_TOKENS":
            excess = sum(pstate["tokens"].values()) - 10
            discard: dict[str, int] = {}
            rem = excess
            # Discard non-gold first, then gold if needed
            for tok in splendor_engine.data.gems + ["gold"]:
                if rem <= 0:
                    break
                take = min(pstate["tokens"][tok], rem)
                if take > 0:
                    discard[tok] = take
                    rem -= take
            action = {"type": "DISCARD_TOKENS", "player": actor, "tokens": discard}

        elif phase == "CHOOSE_NOBLE":
            action = legal[0]

        else:
            # MAIN_ACTION: greedy engine-builder bot
            buys = [a for a in legal if a["type"] == "BUY_CARD"]
            if buys:
                # Prefer highest points, then cheapest total cost
                action = max(
                    buys,
                    key=lambda a: (
                        splendor_engine.data.cards[a["card_id"]]["points"],
                        -sum(splendor_engine.data.cards[a["card_id"]]["cost"].values()),
                    ),
                )
            elif reservations_made < 2 and any(a["type"] == "RESERVE_CARD" and a["source"] == "deck" for a in legal):
                action = next(a for a in legal if a["type"] == "RESERVE_CARD" and a["source"] == "deck")
            else:
                # Pick gems needed by the closest affordable market card
                target_cards = [
                    cid for tier in ("1", "2", "3") for cid in view["market"][tier]
                ]
                def shortfall(cid: str) -> dict[str, int]:
                    card = splendor_engine.data.cards[cid]
                    return {
                        g: max(0, card["cost"].get(g, 0) - pstate["bonuses"][g] - pstate["tokens"][g])
                        for g in splendor_engine.data.gems
                    }

                best_card = min(target_cards, key=lambda cid: sum(shortfall(cid).values()))
                needs = shortfall(best_card)
                take3 = [a for a in legal if a["type"] == "TAKE_THREE_GEMS"]
                take2 = [a for a in legal if a["type"] == "TAKE_TWO_SAME_GEM"]
                if take3:
                    action = max(take3, key=lambda a: sum(1 for g in a["gems"] if needs[g] > 0))
                elif take2:
                    action = max(take2, key=lambda a: needs[a["gem"]])
                else:
                    action = legal[0]

        res = splendor_engine.apply_action(state, action)
        state = res.state

        for ev in res.events_as_dicts():
            jsonschema.validate(instance=ev, schema=EVENT_SCHEMA)
            if ev["type"] == "NOBLE_VISITED":
                nobles_visited += 1
            elif ev["type"] == "CARD_RESERVED":
                reservations_made += 1
            elif ev["type"] == "TOKENS_DISCARDED":
                discards_made += 1

        # Token conservation invariant (4 players => 7 of each gem, 5 gold)
        for g in splendor_engine.data.gems:
            total_g = state["bank"][g] + sum(p["tokens"][g] for p in state["players"].values())
            assert total_g == 7
        total_gold = state["bank"]["gold"] + sum(p["tokens"]["gold"] for p in state["players"].values())
        assert total_gold == 5

        # 90-card conservation invariant
        all_cards = (
            [c for tier in ("1", "2", "3") for c in state["market"][tier]]
            + [c for tier in ("1", "2", "3") for c in state["decks"][tier]]
            + [e["card_id"] for p in state["players"].values() for e in p["reserved"]]
            + [c for p in state["players"].values() for c in p["purchased"]]
        )
        assert len(all_cards) == 90 and len(set(all_cards)) == 90

    outcome = splendor_engine.get_outcome(state)
    assert outcome is not None, "4-player Splendor game should finish within 400 actions"
    assert outcome["reason"] == "FINAL_ROUND_COMPLETED"
    assert state["turn_number"] % 4 == 0, "All 4 players must complete equal turns"
    assert outcome["standings"][0]["points"] >= 15
    assert reservations_made >= 1
    assert nobles_visited >= 1
