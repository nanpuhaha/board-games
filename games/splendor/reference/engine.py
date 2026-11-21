"""Python reference engine for Splendor (Classic)."""

from __future__ import annotations

import copy
import itertools
import json
import random
from pathlib import Path
from typing import Any

from engine.contracts import Action, DomainEvent, GameState, Outcome, PlayerView, RuleError, StepResult

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class SplendorData:
    """Loaded static game data from games/splendor/data/*.json."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        cards_raw = json.loads((data_dir / "cards.json").read_text(encoding="utf-8"))
        nobles_raw = json.loads((data_dir / "nobles.json").read_text(encoding="utf-8"))
        tables = json.loads((data_dir / "setup-tables.json").read_text(encoding="utf-8"))

        self.gems: list[str] = list(tables["gems"])
        self.wild: str = tables["wild"]
        self.all_tokens: list[str] = self.gems + [self.wild]
        self.max_tokens: int = int(tables["max_tokens_per_player"])
        self.max_reserved: int = int(tables["max_reserved_cards"])
        self.market_size: int = int(tables["market_size_per_tier"])
        self.take_two_min_bank: int = int(tables["take_two_min_bank"])
        self.by_player_count: dict[str, dict[str, int]] = tables["by_player_count"]

        self.cards: dict[str, dict[str, Any]] = {c["id"]: c for c in cards_raw["cards"]}
        self.cards_by_tier: dict[str, list[str]] = {"1": [], "2": [], "3": []}
        for card in cards_raw["cards"]:
            self.cards_by_tier[str(card["tier"])].append(card["id"])

        self.nobles: dict[str, dict[str, Any]] = {n["id"]: n for n in nobles_raw["nobles"]}
        self.noble_ids: list[str] = [n["id"] for n in nobles_raw["nobles"]]


class SplendorEngine:
    """Pure-function reference engine implementing the standard GameEngine contract."""

    def __init__(self, data: SplendorData | None = None) -> None:
        self.data = data or SplendorData()

    # ------------------------------------------------------------------
    # Public Contract Methods
    # ------------------------------------------------------------------

    def setup(self, config: dict[str, Any], seed: int) -> StepResult:
        raw_players = config.get("players", [])
        if not (2 <= len(raw_players) <= 4):
            raise RuleError("INVALID_PLAYER_COUNT", "Splendor requires between 2 and 4 players.")

        turn_order: list[str] = []
        seen: set[str] = set()
        for pid in raw_players:
            if not isinstance(pid, str) or not pid or pid in seen:
                raise RuleError("INVALID_CONFIG", f"Invalid or duplicate player id: {pid!r}")
            seen.add(pid)
            turn_order.append(pid)

        target_points = config.get("target_points", 15)
        if not isinstance(target_points, int) or target_points < 1:
            raise RuleError("INVALID_CONFIG", "target_points must be a positive integer.")

        rng = random.Random(seed)
        table = self.data.by_player_count[str(len(turn_order))]

        bank = {g: table["gem_tokens_each"] for g in self.data.gems}
        bank[self.data.wild] = table["gold_tokens"]

        decks: dict[str, list[str]] = {}
        market: dict[str, list[str]] = {}
        for tier in ("1", "2", "3"):
            tier_cards = list(self.data.cards_by_tier[tier])
            rng.shuffle(tier_cards)
            market[tier] = tier_cards[: self.data.market_size]
            decks[tier] = tier_cards[self.data.market_size :]

        noble_pool = list(self.data.noble_ids)
        rng.shuffle(noble_pool)
        nobles = noble_pool[: table["nobles_count"]]

        players_state = {
            pid: {
                "id": pid,
                "tokens": {t: 0 for t in self.data.all_tokens},
                "bonuses": {g: 0 for g in self.data.gems},
                "purchased": [],
                "reserved": [],
                "nobles": [],
                "points": 0,
            }
            for pid in turn_order
        }

        state: GameState = {
            "config": {"target_points": target_points},
            "turn_number": 1,
            "turn_order": turn_order,
            "current_player_index": 0,
            "phase": "MAIN_ACTION",
            "bank": bank,
            "decks": decks,
            "market": market,
            "nobles": nobles,
            "players": players_state,
            "final_round": False,
            "pending_nobles": [],
            "outcome": None,
        }

        events = (
            DomainEvent(
                type="GAME_STARTED",
                visibility="public",
                payload={"turn_order": turn_order, "target_points": target_points, "nobles": list(nobles)},
            ),
            DomainEvent(
                type="TURN_STARTED",
                visibility="public",
                payload={"player": turn_order[0], "turn_number": 1, "final_round": False},
            ),
        )
        return StepResult(state=state, events=events)

    def get_legal_actions(self, state: GameState, player_id: str) -> list[Action]:
        if state["phase"] == "GAME_OVER" or player_id not in state["players"]:
            return []
        if player_id != state["turn_order"][state["current_player_index"]]:
            return []

        phase = state["phase"]
        player = state["players"][player_id]
        actions: list[Action] = []

        if phase == "MAIN_ACTION":
            # 1) TAKE_THREE_GEMS (or fewer if bank has < 3 available colors)
            avail = [g for g in self.data.gems if state["bank"][g] >= 1]
            take_count = min(3, len(avail))
            if take_count >= 1:
                for combo in itertools.combinations(avail, take_count):
                    actions.append({"type": "TAKE_THREE_GEMS", "player": player_id, "gems": list(combo)})

            # 2) TAKE_TWO_SAME_GEM
            for g in self.data.gems:
                if state["bank"][g] >= self.data.take_two_min_bank:
                    actions.append({"type": "TAKE_TWO_SAME_GEM", "player": player_id, "gem": g})

            # 3) RESERVE_CARD
            if len(player["reserved"]) < self.data.max_reserved:
                for tier in ("1", "2", "3"):
                    for card_id in state["market"][tier]:
                        actions.append(
                            {"type": "RESERVE_CARD", "player": player_id, "source": "market", "card_id": card_id}
                        )
                    if state["decks"][tier]:
                        actions.append(
                            {"type": "RESERVE_CARD", "player": player_id, "source": "deck", "tier": int(tier)}
                        )

            # 4) BUY_CARD (market + reserved)
            for tier in ("1", "2", "3"):
                for card_id in state["market"][tier]:
                    if self._can_afford(player, card_id):
                        actions.append(
                            {"type": "BUY_CARD", "player": player_id, "source": "market", "card_id": card_id}
                        )
            for entry in player["reserved"]:
                if self._can_afford(player, entry["card_id"]):
                    actions.append(
                        {"type": "BUY_CARD", "player": player_id, "source": "reserved", "card_id": entry["card_id"]}
                    )

            if not actions:
                actions.append({"type": "PASS_TURN", "player": player_id})

        elif phase == "DISCARD_TOKENS":
            # Provide template action since exact discard multisets can be combinatorial
            actions.append({"type": "DISCARD_TOKENS", "player": player_id})

        elif phase == "CHOOSE_NOBLE":
            for noble_id in state["pending_nobles"]:
                actions.append({"type": "CLAIM_NOBLE", "player": player_id, "noble_id": noble_id})

        return actions

    def apply_action(self, state: GameState, action: Action) -> StepResult:
        if state["phase"] == "GAME_OVER":
            raise RuleError("GAME_ALREADY_OVER", "Game is already over.")

        player_id = action.get("player")
        if player_id not in state["players"]:
            raise RuleError("UNKNOWN_PLAYER", f"Unknown player: {player_id!r}")

        expected = state["turn_order"][state["current_player_index"]]
        if player_id != expected:
            raise RuleError("NOT_YOUR_TURN", f"Expected player {expected!r}, got {player_id!r}")

        action_type = action.get("type")
        next_state = copy.deepcopy(state)
        events: list[DomainEvent] = []

        handlers = {
            "TAKE_THREE_GEMS": self._handle_take_three,
            "TAKE_TWO_SAME_GEM": self._handle_take_two,
            "RESERVE_CARD": self._handle_reserve,
            "BUY_CARD": self._handle_buy,
            "PASS_TURN": self._handle_pass_turn,
            "DISCARD_TOKENS": self._handle_discard,
            "CLAIM_NOBLE": self._handle_claim_noble,
        }
        handler = handlers.get(action_type)
        if handler is None:
            raise RuleError("UNKNOWN_ACTION", f"Unknown action type: {action_type!r}")

        handler(next_state, action, events)
        return StepResult(state=next_state, events=tuple(events))

    def get_player_view(self, state: GameState, player_id: str) -> PlayerView:
        if player_id not in state["players"]:
            raise RuleError("UNKNOWN_PLAYER", f"Unknown player: {player_id!r}")

        players_view: dict[str, Any] = {}
        for pid, pstate in state["players"].items():
            reserved_view = []
            for entry in pstate["reserved"]:
                if entry["face_down"] and pid != player_id:
                    reserved_view.append({"hidden": True, "tier": entry["tier"], "face_down": True})
                else:
                    reserved_view.append(copy.deepcopy(entry))
            players_view[pid] = {
                "id": pstate["id"],
                "tokens": dict(pstate["tokens"]),
                "bonuses": dict(pstate["bonuses"]),
                "purchased": list(pstate["purchased"]),
                "reserved": reserved_view,
                "nobles": list(pstate["nobles"]),
                "points": pstate["points"],
            }

        return {
            "config": copy.deepcopy(state["config"]),
            "turn_number": state["turn_number"],
            "turn_order": list(state["turn_order"]),
            "current_player_index": state["current_player_index"],
            "phase": state["phase"],
            "bank": dict(state["bank"]),
            "deck_counts": {tier: len(cards) for tier, cards in state["decks"].items()},
            "market": copy.deepcopy(state["market"]),
            "nobles": list(state["nobles"]),
            "players": players_view,
            "final_round": state["final_round"],
            "pending_nobles": list(state["pending_nobles"]),
            "outcome": copy.deepcopy(state["outcome"]),
        }

    def get_outcome(self, state: GameState) -> Outcome | None:
        return copy.deepcopy(state["outcome"])

    # ------------------------------------------------------------------
    # Action Handlers
    # ------------------------------------------------------------------

    def _handle_take_three(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"MAIN_ACTION"})
        player_id = action["player"]
        gems = action.get("gems")

        if not isinstance(gems, list) or len(gems) != len(set(gems)) or any(g not in self.data.gems for g in gems):
            raise RuleError("INVALID_GEM_SELECTION", "gems must be distinct non-gold gem colors.")

        avail = [g for g in self.data.gems if state["bank"][g] >= 1]
        if not avail:
            raise RuleError("INSUFFICIENT_BANK_TOKENS", "No gem tokens available in bank.")
        expected_len = min(3, len(avail))
        if len(gems) != expected_len:
            raise RuleError("INVALID_GEM_SELECTION", f"Must select exactly {expected_len} distinct available gem(s).")
        if any(state["bank"][g] < 1 for g in gems):
            raise RuleError("INSUFFICIENT_BANK_TOKENS", "One or more selected gems are unavailable in bank.")

        taken: dict[str, int] = {}
        for g in gems:
            state["bank"][g] -= 1
            state["players"][player_id]["tokens"][g] += 1
            taken[g] = 1

        events.append(DomainEvent(type="TOKENS_TAKEN", visibility="public", payload={"player": player_id, "tokens": taken}))
        self._after_main_action(state, player_id, events)

    def _handle_take_two(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"MAIN_ACTION"})
        player_id = action["player"]
        gem = action.get("gem")

        if gem not in self.data.gems:
            raise RuleError("INVALID_GEM_SELECTION", f"Invalid gem color: {gem!r}")
        if state["bank"][gem] < self.data.take_two_min_bank:
            raise RuleError("INSUFFICIENT_BANK_TOKENS", f"Need at least {self.data.take_two_min_bank} {gem} in bank to take 2.")

        state["bank"][gem] -= 2
        state["players"][player_id]["tokens"][gem] += 2

        events.append(
            DomainEvent(type="TOKENS_TAKEN", visibility="public", payload={"player": player_id, "tokens": {gem: 2}})
        )
        self._after_main_action(state, player_id, events)

    def _handle_reserve(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"MAIN_ACTION"})
        player_id = action["player"]
        player = state["players"][player_id]

        if len(player["reserved"]) >= self.data.max_reserved:
            raise RuleError("RESERVE_LIMIT_REACHED", "Player already has maximum 3 reserved cards.")

        source = action.get("source")
        gold_gained = 0
        if state["bank"][self.data.wild] > 0:
            state["bank"][self.data.wild] -= 1
            player["tokens"][self.data.wild] += 1
            gold_gained = 1

        if source == "market":
            card_id = action.get("card_id")
            tier_found = self._remove_from_market(state, card_id)
            if tier_found is None:
                raise RuleError("CARD_NOT_IN_MARKET", f"Card {card_id!r} is not in the market.")

            player["reserved"].append({"card_id": card_id, "tier": int(tier_found), "face_down": False})
            events.append(
                DomainEvent(
                    type="CARD_RESERVED",
                    visibility="public",
                    payload={
                        "player": player_id,
                        "source": "market",
                        "tier": int(tier_found),
                        "card_id": card_id,
                        "gold_gained": gold_gained,
                    },
                )
            )
            self._refill_market(state, tier_found, events)

        elif source == "deck":
            tier = action.get("tier")
            tier_key = str(tier)
            if tier_key not in ("1", "2", "3"):
                raise RuleError("INVALID_TIER", f"Invalid tier: {tier!r}")
            if not state["decks"][tier_key]:
                raise RuleError("EMPTY_DECK", f"Tier {tier} deck is empty.")

            card_id = state["decks"][tier_key].pop(0)
            player["reserved"].append({"card_id": card_id, "tier": int(tier_key), "face_down": True})
            events.append(
                DomainEvent(
                    type="CARD_RESERVED",
                    visibility="public",
                    payload={"player": player_id, "source": "deck", "tier": int(tier_key), "gold_gained": gold_gained},
                )
            )
            events.append(
                DomainEvent(
                    type="BLIND_CARD_RESERVED",
                    visibility="private",
                    recipients=(player_id,),
                    payload={"player": player_id, "tier": int(tier_key), "card_id": card_id},
                )
            )
        else:
            raise RuleError("INVALID_SOURCE", f"Invalid reserve source: {source!r}")

        self._after_main_action(state, player_id, events)

    def _handle_buy(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"MAIN_ACTION"})
        player_id = action["player"]
        player = state["players"][player_id]
        source = action.get("source")
        card_id = action.get("card_id")

        if source == "market":
            tier_found = self._find_in_market(state, card_id)
            if tier_found is None:
                raise RuleError("CARD_NOT_IN_MARKET", f"Card {card_id!r} is not in the market.")
        elif source == "reserved":
            res_idx = next((i for i, e in enumerate(player["reserved"]) if e["card_id"] == card_id), None)
            if res_idx is None:
                raise RuleError("CARD_NOT_RESERVED", f"Card {card_id!r} is not reserved by {player_id!r}.")
            tier_found = None
        else:
            raise RuleError("INVALID_SOURCE", f"Invalid buy source: {source!r}")

        paid = self._compute_payment(player, card_id)
        if paid is None:
            raise RuleError("INSUFFICIENT_RESOURCES", f"Cannot afford card {card_id!r}.")

        for tok, qty in paid.items():
            if qty > 0:
                player["tokens"][tok] -= qty
                state["bank"][tok] += qty

        if source == "market":
            assert tier_found is not None
            state["market"][tier_found].remove(card_id)
        else:
            player["reserved"].pop(res_idx)

        card = self.data.cards[card_id]
        player["purchased"].append(card_id)
        player["bonuses"][card["bonus"]] += 1
        player["points"] += card["points"]

        events.append(
            DomainEvent(
                type="CARD_PURCHASED",
                visibility="public",
                payload={
                    "player": player_id,
                    "source": source,
                    "card_id": card_id,
                    "paid": {k: v for k, v in paid.items() if v > 0},
                    "points_gained": card["points"],
                },
            )
        )

        if source == "market":
            assert tier_found is not None
            self._refill_market(state, tier_found, events)

        self._after_main_action(state, player_id, events)

    def _handle_pass_turn(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"MAIN_ACTION"})
        player_id = action["player"]
        legal = self.get_legal_actions(state, player_id)
        if not (len(legal) == 1 and legal[0]["type"] == "PASS_TURN"):
            raise RuleError("CANNOT_PASS", "Cannot pass while legal main actions exist.")
        events.append(DomainEvent(type="TURN_PASSED", visibility="public", payload={"player": player_id}))
        self._after_main_action(state, player_id, events)

    def _handle_discard(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"DISCARD_TOKENS"})
        player_id = action["player"]
        player = state["players"][player_id]
        discard = action.get("tokens")

        if not isinstance(discard, dict) or not discard:
            raise RuleError("INVALID_DISCARD", "Must provide a non-empty token discard map.")

        total_discard = 0
        for tok, qty in discard.items():
            if tok not in self.data.all_tokens or not isinstance(qty, int) or qty <= 0:
                raise RuleError("INVALID_DISCARD", f"Invalid discard entry: {tok!r}: {qty!r}")
            if player["tokens"][tok] < qty:
                raise RuleError("INVALID_DISCARD", f"Player lacks {qty} of {tok!r}.")
            total_discard += qty

        current_total = sum(player["tokens"].values())
        if current_total - total_discard != self.data.max_tokens:
            raise RuleError(
                "INVALID_DISCARD_COUNT",
                f"Must discard exactly {current_total - self.data.max_tokens} token(s) to reach {self.data.max_tokens}.",
            )

        for tok, qty in discard.items():
            player["tokens"][tok] -= qty
            state["bank"][tok] += qty

        events.append(
            DomainEvent(type="TOKENS_DISCARDED", visibility="public", payload={"player": player_id, "tokens": dict(discard)})
        )
        self._check_nobles_and_end_turn(state, player_id, events)

    def _handle_claim_noble(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"CHOOSE_NOBLE"})
        player_id = action["player"]
        noble_id = action.get("noble_id")

        if noble_id not in state["pending_nobles"]:
            raise RuleError("INVALID_NOBLE", f"Noble {noble_id!r} is not eligible to claim.")

        self._grant_noble(state, player_id, noble_id, events)
        state["pending_nobles"] = []
        self._finalize_turn(state, player_id, events)

    # ------------------------------------------------------------------
    # Turn End Pipeline & Helpers
    # ------------------------------------------------------------------

    def _after_main_action(self, state: GameState, player_id: str, events: list[DomainEvent]) -> None:
        total_tokens = sum(state["players"][player_id]["tokens"].values())
        if total_tokens > self.data.max_tokens:
            state["phase"] = "DISCARD_TOKENS"
            return
        self._check_nobles_and_end_turn(state, player_id, events)

    def _check_nobles_and_end_turn(self, state: GameState, player_id: str, events: list[DomainEvent]) -> None:
        bonuses = state["players"][player_id]["bonuses"]
        eligible = [
            nid
            for nid in state["nobles"]
            if all(bonuses[g] >= req for g, req in self.data.nobles[nid]["requirements"].items())
        ]
        if len(eligible) >= 2:
            state["pending_nobles"] = eligible
            state["phase"] = "CHOOSE_NOBLE"
            return
        if len(eligible) == 1:
            self._grant_noble(state, player_id, eligible[0], events)

        self._finalize_turn(state, player_id, events)

    def _grant_noble(self, state: GameState, player_id: str, noble_id: str, events: list[DomainEvent]) -> None:
        state["nobles"].remove(noble_id)
        pts = self.data.nobles[noble_id]["points"]
        state["players"][player_id]["nobles"].append(noble_id)
        state["players"][player_id]["points"] += pts
        events.append(
            DomainEvent(
                type="NOBLE_VISITED",
                visibility="public",
                payload={"player": player_id, "noble_id": noble_id, "points_gained": pts},
            )
        )

    def _finalize_turn(self, state: GameState, player_id: str, events: list[DomainEvent]) -> None:
        target = state["config"]["target_points"]
        if not state["final_round"] and state["players"][player_id]["points"] >= target:
            state["final_round"] = True
            events.append(
                DomainEvent(
                    type="FINAL_ROUND_TRIGGERED",
                    visibility="public",
                    payload={"triggered_by": player_id, "points": state["players"][player_id]["points"]},
                )
            )

        events.append(DomainEvent(type="TURN_ENDED", visibility="public", payload={"player": player_id}))

        is_last_in_round = state["current_player_index"] == len(state["turn_order"]) - 1
        if state["final_round"] and is_last_in_round:
            outcome = self._compute_outcome(state)
            state["outcome"] = outcome
            state["phase"] = "GAME_OVER"
            events.append(DomainEvent(type="GAME_ENDED", visibility="public", payload=copy.deepcopy(outcome)))
            return

        state["current_player_index"] = (state["current_player_index"] + 1) % len(state["turn_order"])
        state["turn_number"] += 1
        state["phase"] = "MAIN_ACTION"
        next_player = state["turn_order"][state["current_player_index"]]
        events.append(
            DomainEvent(
                type="TURN_STARTED",
                visibility="public",
                payload={"player": next_player, "turn_number": state["turn_number"], "final_round": state["final_round"]},
            )
        )

    def _compute_outcome(self, state: GameState) -> Outcome:
        standings = [
            {
                "player": pid,
                "points": state["players"][pid]["points"],
                "purchased_count": len(state["players"][pid]["purchased"]),
                "nobles_count": len(state["players"][pid]["nobles"]),
            }
            for pid in state["turn_order"]
        ]
        standings.sort(key=lambda s: (-s["points"], s["purchased_count"]))
        top = standings[0]
        winners = [
            s["player"]
            for s in standings
            if s["points"] == top["points"] and s["purchased_count"] == top["purchased_count"]
        ]
        return {
            "winner": winners[0] if len(winners) == 1 else None,
            "winners": winners,
            "reason": "FINAL_ROUND_COMPLETED",
            "standings": standings,
        }

    def _require_phase(self, state: GameState, allowed: set[str]) -> None:
        if state["phase"] not in allowed:
            raise RuleError(
                "INVALID_PHASE",
                f"Action not allowed in phase {state['phase']!r}; allowed: {sorted(allowed)}",
            )

    def _find_in_market(self, state: GameState, card_id: Any) -> str | None:
        for tier in ("1", "2", "3"):
            if card_id in state["market"][tier]:
                return tier
        return None

    def _remove_from_market(self, state: GameState, card_id: Any) -> str | None:
        tier = self._find_in_market(state, card_id)
        if tier is not None:
            state["market"][tier].remove(card_id)
        return tier

    def _refill_market(self, state: GameState, tier: str, events: list[DomainEvent]) -> None:
        if state["decks"][tier]:
            new_card = state["decks"][tier].pop(0)
            state["market"][tier].append(new_card)
            events.append(
                DomainEvent(
                    type="CARD_REVEALED_TO_MARKET",
                    visibility="public",
                    payload={"tier": int(tier), "card_id": new_card},
                )
            )

    def _compute_payment(self, player: dict[str, Any], card_id: str) -> dict[str, int] | None:
        card = self.data.cards[card_id]
        paid: dict[str, int] = {t: 0 for t in self.data.all_tokens}
        gold_needed = 0
        for g in self.data.gems:
            cost_g = card["cost"].get(g, 0)
            net = max(0, cost_g - player["bonuses"][g])
            use_g = min(player["tokens"][g], net)
            paid[g] = use_g
            gold_needed += net - use_g
        if player["tokens"][self.data.wild] < gold_needed:
            return None
        paid[self.data.wild] = gold_needed
        return paid

    def _can_afford(self, player: dict[str, Any], card_id: str) -> bool:
        return self._compute_payment(player, card_id) is not None
