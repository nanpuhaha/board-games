"""Python reference engine for Clue (Classic + Question Mark Bonus Cards)."""

from __future__ import annotations

import copy
import json
import random
from collections import deque
from pathlib import Path
from typing import Any

from engine.contracts import Action, DomainEvent, GameState, Outcome, PlayerView, RuleError, StepResult

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class ClueData:
    """Loaded static game data from games/clue/data/*.json."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        cards = json.loads((data_dir / "cards.json").read_text(encoding="utf-8"))
        board = json.loads((data_dir / "board.json").read_text(encoding="utf-8"))
        bonus = json.loads((data_dir / "bonus-cards.json").read_text(encoding="utf-8"))

        self.suspects: list[str] = [s["id"] for s in cards["suspects"]]
        self.suspect_order: dict[str, int] = {s["id"]: s["turn_order"] for s in cards["suspects"]}
        self.weapons: list[str] = [w["id"] for w in cards["weapons"]]
        self.rooms: list[str] = [r["id"] for r in cards["rooms"]]

        self.width: int = board["width"]
        self.height: int = board["height"]
        self.grid: list[str] = board["grid"]
        self.start_positions: dict[str, tuple[int, int]] = {
            k: (v[0], v[1]) for k, v in board["start_positions"].items()
        }
        self.room_doorways: dict[str, list[tuple[int, int]]] = {
            room: [(d[0], d[1]) for d in info["doorways"]] for room, info in board["rooms"].items()
        }
        self.secret_passages: dict[str, str | None] = {
            room: info["secret_passage_to"] for room, info in board["rooms"].items()
        }
        self.walkable: set[tuple[int, int]] = {
            (x, y)
            for y, row in enumerate(self.grid)
            for x, ch in enumerate(row)
            if ch in (".", "?")
        }
        self.question_marks: set[tuple[int, int]] = {
            (x, y)
            for y, row in enumerate(self.grid)
            for x, ch in enumerate(row)
            if ch == "?"
        }

        self.bonus_cards: dict[str, dict[str, Any]] = {c["id"]: c for c in bonus["cards"]}
        self.bonus_card_ids: list[str] = [c["id"] for c in bonus["cards"]]


class ClueEngine:
    """Pure-function reference engine implementing the standard GameEngine contract."""

    def __init__(self, data: ClueData | None = None) -> None:
        self.data = data or ClueData()

    # ------------------------------------------------------------------
    # Public Contract Methods
    # ------------------------------------------------------------------

    def setup(self, config: dict[str, Any], seed: int) -> StepResult:
        raw_players = config.get("players", [])
        if not (3 <= len(raw_players) <= 6):
            raise RuleError("INVALID_PLAYER_COUNT", "Clue requires between 3 and 6 players.")

        seen_ids: set[str] = set()
        seen_suspects: set[str] = set()
        for entry in raw_players:
            pid = entry.get("id")
            suspect = entry.get("suspect")
            if not pid or pid in seen_ids:
                raise RuleError("INVALID_CONFIG", f"Duplicate or empty player id: {pid!r}")
            if suspect not in self.data.suspects or suspect in seen_suspects:
                raise RuleError("INVALID_CONFIG", f"Invalid or duplicate suspect: {suspect!r}")
            seen_ids.add(pid)
            seen_suspects.add(suspect)

        enable_bonus = bool(config.get("enable_bonus_cards", True))
        accusation_requires_room = bool(config.get("accusation_requires_room", False))

        rng = random.Random(seed)

        sorted_players = sorted(raw_players, key=lambda p: self.data.suspect_order[p["suspect"]])
        turn_order = [p["id"] for p in sorted_players]

        tokens = {
            suspect: {"kind": "hallway", "x": pos[0], "y": pos[1]}
            for suspect, pos in self.data.start_positions.items()
        }

        shuffled_rooms_for_weapons = list(self.data.rooms)
        rng.shuffle(shuffled_rooms_for_weapons)
        weapons = {
            weapon: shuffled_rooms_for_weapons[i] for i, weapon in enumerate(self.data.weapons)
        }

        suspect_deck = list(self.data.suspects)
        weapon_deck = list(self.data.weapons)
        room_deck = list(self.data.rooms)
        rng.shuffle(suspect_deck)
        rng.shuffle(weapon_deck)
        rng.shuffle(room_deck)

        envelope = {
            "suspect": suspect_deck.pop(0),
            "weapon": weapon_deck.pop(0),
            "room": room_deck.pop(0),
        }

        remaining = suspect_deck + weapon_deck + room_deck
        rng.shuffle(remaining)

        hands: dict[str, list[str]] = {pid: [] for pid in turn_order}
        for idx, card in enumerate(remaining):
            hands[turn_order[idx % len(turn_order)]].append(card)

        bonus_deck = list(self.data.bonus_card_ids) if enable_bonus else []
        if bonus_deck:
            rng.shuffle(bonus_deck)

        players_state = {
            p["id"]: {
                "id": p["id"],
                "suspect": p["suspect"],
                "hand": hands[p["id"]],
                "eliminated": False,
                "pulled_into_room": False,
            }
            for p in sorted_players
        }

        state: GameState = {
            "config": {
                "enable_bonus_cards": enable_bonus,
                "accusation_requires_room": accusation_requires_room,
            },
            "rng_state": rng.randrange(0, 2**31),
            "turn_number": 1,
            "turn_order": turn_order,
            "current_player_index": 0,
            "phase": "TURN_START",
            "players": players_state,
            "tokens": tokens,
            "weapons": weapons,
            "envelope": envelope,
            "bonus_deck": bonus_deck,
            "dice": None,
            "movement_remaining": 0,
            "extra_turn_pending": False,
            "pending_suggestion": None,
            "pending_bonus": None,
            "public_revealed_cards": [],
            "outcome": None,
        }

        events: list[DomainEvent] = [
            DomainEvent(
                type="GAME_STARTED",
                visibility="public",
                payload={"turn_order": turn_order, "enable_bonus_cards": enable_bonus},
            ),
            *[
                DomainEvent(
                    type="CARDS_DEALT",
                    visibility="private",
                    recipients=(pid,),
                    payload={"player": pid, "cards": list(hands[pid])},
                )
                for pid in turn_order
            ],
            DomainEvent(
                type="TURN_STARTED",
                visibility="public",
                payload={"player": turn_order[0], "turn_number": 1},
            ),
        ]

        return StepResult(state=state, events=tuple(events))

    def get_legal_actions(self, state: GameState, player_id: str) -> list[Action]:
        if state["phase"] == "GAME_OVER" or player_id not in state["players"]:
            return []

        phase = state["phase"]
        actor = self._expected_actor(state)
        if player_id != actor:
            return []

        actions: list[Action] = []
        player = state["players"][player_id]
        loc = state["tokens"][player["suspect"]]

        if phase == "TURN_START":
            actions.append({"type": "ROLL_DICE", "player": player_id})
            if loc["kind"] == "room" and self.data.secret_passages.get(loc["room"]):
                actions.append({"type": "USE_SECRET_PASSAGE", "player": player_id})
            if loc["kind"] == "room" and player["pulled_into_room"]:
                actions.append({"type": "STAY_FOR_SUGGESTION", "player": player_id})
            if self._can_accuse(state, player_id):
                actions.append({"type": "MAKE_ACCUSATION", "player": player_id})

        elif phase in ("MOVE", "BONUS_MOVE"):
            hallways, rooms = self._reachable_destinations(state, player["suspect"], state["movement_remaining"])
            for x, y in sorted(hallways):
                actions.append({"type": "MOVE_TO_HALLWAY", "player": player_id, "x": x, "y": y})
            for room in sorted(rooms):
                actions.append({"type": "MOVE_TO_ROOM", "player": player_id, "room": room})
            if not actions:
                actions.append({"type": "END_TURN", "player": player_id})

        elif phase == "BONUS_RESOLVE":
            pb = state["pending_bonus"]
            assert pb is not None
            step = pb["step"]
            if step == "CHOOSE_ROOM":
                for room in self.data.rooms:
                    actions.append({"type": "BONUS_CHOOSE_ROOM", "player": player_id, "room": room})
            elif step == "CHOOSE_TARGET":
                for pid in state["turn_order"]:
                    if pid != player_id:
                        actions.append({"type": "BONUS_CHOOSE_TARGET", "player": player_id, "target_player": pid})
            elif step == "RESPOND_CARD":
                for card in state["players"][player_id]["hand"]:
                    actions.append({"type": "BONUS_RESPOND_CARD", "player": player_id, "card": card})
            elif step == "CHOOSE_SUGGESTION":
                actions.append({"type": "BONUS_MAKE_SUGGESTION", "player": player_id})

        elif phase == "POST_MOVE":
            if loc["kind"] == "room":
                actions.append({"type": "MAKE_SUGGESTION", "player": player_id})
            if self._can_accuse(state, player_id):
                actions.append({"type": "MAKE_ACCUSATION", "player": player_id})
            actions.append({"type": "END_TURN", "player": player_id})

        elif phase == "DISPROVE":
            ps = state["pending_suggestion"]
            assert ps is not None
            needed = {ps["suspect"], ps["weapon"], ps["room"]}
            matching = [c for c in player["hand"] if c in needed]
            if matching:
                for card in matching:
                    actions.append({"type": "SHOW_DISPROVE_CARD", "player": player_id, "card": card})
            else:
                actions.append({"type": "PASS_DISPROVE", "player": player_id})

        elif phase == "POST_SUGGESTION":
            if self._can_accuse(state, player_id):
                actions.append({"type": "MAKE_ACCUSATION", "player": player_id})
            actions.append({"type": "END_TURN", "player": player_id})

        return actions

    def apply_action(self, state: GameState, action: Action) -> StepResult:
        if state["phase"] == "GAME_OVER":
            raise RuleError("GAME_ALREADY_OVER", "Game is already over.")

        player_id = action.get("player")
        if player_id not in state["players"]:
            raise RuleError("UNKNOWN_PLAYER", f"Unknown player: {player_id!r}")

        expected_actor = self._expected_actor(state)
        if player_id != expected_actor:
            raise RuleError("NOT_YOUR_TURN", f"Expected actor {expected_actor!r}, got {player_id!r}")

        action_type = action.get("type")
        next_state = copy.deepcopy(state)
        events: list[DomainEvent] = []

        handler_map = {
            "ROLL_DICE": self._handle_roll_dice,
            "USE_SECRET_PASSAGE": self._handle_secret_passage,
            "STAY_FOR_SUGGESTION": self._handle_stay_for_suggestion,
            "MOVE_TO_HALLWAY": self._handle_move_to_hallway,
            "MOVE_TO_ROOM": self._handle_move_to_room,
            "BONUS_CHOOSE_ROOM": self._handle_bonus_choose_room,
            "BONUS_CHOOSE_TARGET": self._handle_bonus_choose_target,
            "BONUS_RESPOND_CARD": self._handle_bonus_respond_card,
            "BONUS_MAKE_SUGGESTION": self._handle_bonus_make_suggestion,
            "MAKE_SUGGESTION": self._handle_make_suggestion,
            "SHOW_DISPROVE_CARD": self._handle_show_disprove_card,
            "PASS_DISPROVE": self._handle_pass_disprove,
            "MAKE_ACCUSATION": self._handle_make_accusation,
            "END_TURN": self._handle_end_turn,
        }

        handler = handler_map.get(action_type)
        if handler is None:
            raise RuleError("UNKNOWN_ACTION", f"Unknown action type: {action_type!r}")

        handler(next_state, action, events)
        return StepResult(state=next_state, events=tuple(events))

    def get_player_view(self, state: GameState, player_id: str) -> PlayerView:
        if player_id not in state["players"]:
            raise RuleError("UNKNOWN_PLAYER", f"Unknown player: {player_id!r}")

        players_view: dict[str, Any] = {}
        for pid, pstate in state["players"].items():
            entry: dict[str, Any] = {
                "id": pstate["id"],
                "suspect": pstate["suspect"],
                "eliminated": pstate["eliminated"],
                "pulled_into_room": pstate["pulled_into_room"],
                "hand_count": len(pstate["hand"]),
            }
            if pid == player_id:
                entry["hand"] = list(pstate["hand"])
            players_view[pid] = entry

        view: PlayerView = {
            "config": copy.deepcopy(state["config"]),
            "turn_number": state["turn_number"],
            "turn_order": list(state["turn_order"]),
            "current_player_index": state["current_player_index"],
            "phase": state["phase"],
            "players": players_view,
            "tokens": copy.deepcopy(state["tokens"]),
            "weapons": copy.deepcopy(state["weapons"]),
            "bonus_deck_count": len(state["bonus_deck"]),
            "dice": list(state["dice"]) if state["dice"] is not None else None,
            "movement_remaining": state["movement_remaining"],
            "extra_turn_pending": state["extra_turn_pending"],
            "pending_suggestion": copy.deepcopy(state["pending_suggestion"]),
            "pending_bonus": copy.deepcopy(state["pending_bonus"]),
            "public_revealed_cards": copy.deepcopy(state["public_revealed_cards"]),
            "outcome": copy.deepcopy(state["outcome"]),
        }
        return view

    def get_outcome(self, state: GameState) -> Outcome | None:
        return copy.deepcopy(state["outcome"])

    # ------------------------------------------------------------------
    # Action Handlers
    # ------------------------------------------------------------------

    def _handle_roll_dice(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"TURN_START"})
        player_id = action["player"]

        dice_override = action.get("dice_override")
        if dice_override is not None:
            if (
                not isinstance(dice_override, list)
                or len(dice_override) != 2
                or not all(isinstance(d, int) and 1 <= d <= 6 for d in dice_override)
            ):
                raise RuleError("INVALID_DICE", "dice_override must be two integers between 1 and 6.")
            d1, d2 = dice_override[0], dice_override[1]
        else:
            rng = random.Random(state["rng_state"])
            d1 = rng.randint(1, 6)
            d2 = rng.randint(1, 6)
            state["rng_state"] = rng.randrange(0, 2**31)

        state["dice"] = [d1, d2]
        state["movement_remaining"] = d1 + d2
        state["players"][player_id]["pulled_into_room"] = False
        state["phase"] = "MOVE"

        events.append(
            DomainEvent(
                type="DICE_ROLLED",
                visibility="public",
                payload={"player": player_id, "dice": [d1, d2], "total": d1 + d2},
            )
        )

    def _handle_secret_passage(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"TURN_START"})
        player_id = action["player"]
        suspect = state["players"][player_id]["suspect"]
        loc = state["tokens"][suspect]

        if loc["kind"] != "room":
            raise RuleError("NOT_IN_ROOM", "Must be in a room to use a secret passage.")
        from_room = loc["room"]
        to_room = self.data.secret_passages.get(from_room)
        if not to_room:
            raise RuleError("NO_SECRET_PASSAGE", f"Room {from_room!r} has no secret passage.")

        dest = {"kind": "room", "room": to_room}
        state["tokens"][suspect] = dest
        state["players"][player_id]["pulled_into_room"] = False
        state["phase"] = "POST_MOVE"

        events.append(
            DomainEvent(
                type="SECRET_PASSAGE_USED",
                visibility="public",
                payload={"player": player_id, "from_room": from_room, "to_room": to_room},
            )
        )
        events.append(
            DomainEvent(
                type="TOKEN_MOVED",
                visibility="public",
                payload={"suspect": suspect, "from": loc, "to": dest, "reason": "secret_passage"},
            )
        )

    def _handle_stay_for_suggestion(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"TURN_START"})
        player_id = action["player"]
        player = state["players"][player_id]
        loc = state["tokens"][player["suspect"]]

        if loc["kind"] != "room" or not player["pulled_into_room"]:
            raise RuleError(
                "CANNOT_STAY_WITHOUT_PULL",
                "You may only stay without rolling if pulled into this room by another player's suggestion.",
            )

        player["pulled_into_room"] = False
        state["phase"] = "POST_MOVE"
        events.append(
            DomainEvent(
                type="STAYED_IN_ROOM",
                visibility="public",
                payload={"player": player_id, "room": loc["room"]},
            )
        )

    def _handle_move_to_hallway(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"MOVE", "BONUS_MOVE"})
        player_id = action["player"]
        suspect = state["players"][player_id]["suspect"]
        x, y = action.get("x"), action.get("y")

        if not isinstance(x, int) or not isinstance(y, int) or (x, y) not in self.data.walkable:
            raise RuleError("INVALID_DESTINATION", f"({x}, {y}) is not a valid hallway square.")

        occupied = self._occupied_hallways(state, exclude_suspect=suspect)
        if (x, y) in occupied:
            raise RuleError("TARGET_OCCUPIED", f"Hallway square ({x}, {y}) is occupied.")

        hallways, _ = self._reachable_destinations(state, suspect, state["movement_remaining"])
        if (x, y) not in hallways:
            raise RuleError("UNREACHABLE_DESTINATION", f"Square ({x}, {y}) is unreachable with {state['movement_remaining']} steps.")

        prev_loc = state["tokens"][suspect]
        new_loc = {"kind": "hallway", "x": x, "y": y}
        is_bonus_move = state["phase"] == "BONUS_MOVE"

        state["tokens"][suspect] = new_loc
        state["movement_remaining"] = 0

        events.append(
            DomainEvent(
                type="TOKEN_MOVED",
                visibility="public",
                payload={"suspect": suspect, "from": prev_loc, "to": new_loc, "reason": "move"},
            )
        )

        if (
            not is_bonus_move
            and state["config"]["enable_bonus_cards"]
            and (x, y) in self.data.question_marks
            and state["bonus_deck"]
        ):
            self._trigger_bonus_card(state, player_id, events)
        else:
            state["phase"] = "POST_MOVE"

    def _handle_move_to_room(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"MOVE", "BONUS_MOVE"})
        player_id = action["player"]
        suspect = state["players"][player_id]["suspect"]
        room = action.get("room")

        if room not in self.data.rooms:
            raise RuleError("INVALID_ROOM", f"Unknown room: {room!r}")

        prev_loc = state["tokens"][suspect]
        if prev_loc["kind"] == "room" and prev_loc["room"] == room:
            raise RuleError("ALREADY_IN_ROOM", f"Already in room {room!r}.")

        _, reachable_rooms = self._reachable_destinations(state, suspect, state["movement_remaining"])
        if room not in reachable_rooms:
            raise RuleError("UNREACHABLE_DESTINATION", f"Room {room!r} is unreachable with {state['movement_remaining']} steps.")

        new_loc = {"kind": "room", "room": room}
        state["tokens"][suspect] = new_loc
        state["movement_remaining"] = 0
        state["phase"] = "POST_MOVE"

        events.append(
            DomainEvent(
                type="TOKEN_MOVED",
                visibility="public",
                payload={"suspect": suspect, "from": prev_loc, "to": new_loc, "reason": "move"},
            )
        )

    def _trigger_bonus_card(self, state: GameState, player_id: str, events: list[DomainEvent]) -> None:
        card_id = state["bonus_deck"].pop(0)
        state["bonus_deck"].append(card_id)  # Recycle to bottom of deck
        card_def = self.data.bonus_cards[card_id]
        effect = card_def["effect"]

        events.append(
            DomainEvent(
                type="BONUS_CARD_DRAWN",
                visibility="public",
                payload={"player": player_id, "card_id": card_id, "effect": effect},
            )
        )

        if effect == "extra_turn":
            state["extra_turn_pending"] = True
            state["phase"] = "POST_MOVE"
            events.append(
                DomainEvent(
                    type="BONUS_EFFECT_RESOLVED",
                    visibility="public",
                    payload={"player": player_id, "card_id": card_id, "effect": effect},
                )
            )
        elif effect == "bonus_move":
            steps = int(card_def["params"].get("steps", 6))
            state["movement_remaining"] = steps
            state["phase"] = "BONUS_MOVE"
            events.append(
                DomainEvent(
                    type="BONUS_EFFECT_RESOLVED",
                    visibility="public",
                    payload={"player": player_id, "card_id": card_id, "effect": effect, "steps": steps},
                )
            )
        elif effect == "teleport_any_room":
            state["pending_bonus"] = {
                "card_id": card_id,
                "effect": effect,
                "drawer": player_id,
                "target_player": None,
                "step": "CHOOSE_ROOM",
            }
            state["phase"] = "BONUS_RESOLVE"
        elif effect in ("peek_opponent_card", "force_public_reveal", "swap_position"):
            state["pending_bonus"] = {
                "card_id": card_id,
                "effect": effect,
                "drawer": player_id,
                "target_player": None,
                "step": "CHOOSE_TARGET",
            }
            state["phase"] = "BONUS_RESOLVE"
        elif effect == "peek_left_card":
            idx = state["turn_order"].index(player_id)
            left_player = state["turn_order"][(idx + 1) % len(state["turn_order"])]
            if not state["players"][left_player]["hand"]:
                state["phase"] = "POST_MOVE"
                events.append(
                    DomainEvent(
                        type="BONUS_EFFECT_RESOLVED",
                        visibility="public",
                        payload={"player": player_id, "card_id": card_id, "effect": effect},
                    )
                )
            else:
                state["pending_bonus"] = {
                    "card_id": card_id,
                    "effect": effect,
                    "drawer": player_id,
                    "target_player": left_player,
                    "step": "RESPOND_CARD",
                }
                state["phase"] = "BONUS_RESOLVE"
        elif effect == "free_suggestion":
            state["pending_bonus"] = {
                "card_id": card_id,
                "effect": effect,
                "drawer": player_id,
                "target_player": None,
                "step": "CHOOSE_SUGGESTION",
            }
            state["phase"] = "BONUS_RESOLVE"
        else:
            raise RuleError("UNKNOWN_BONUS_EFFECT", f"Unsupported bonus effect: {effect!r}")

    def _handle_bonus_choose_room(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"BONUS_RESOLVE"})
        pb = state["pending_bonus"]
        if pb is None or pb["step"] != "CHOOSE_ROOM":
            raise RuleError("INVALID_BONUS_STEP", "Not awaiting room selection.")

        room = action.get("room")
        if room not in self.data.rooms:
            raise RuleError("INVALID_ROOM", f"Unknown room: {room!r}")

        player_id = action["player"]
        suspect = state["players"][player_id]["suspect"]
        prev_loc = state["tokens"][suspect]
        new_loc = {"kind": "room", "room": room}
        state["tokens"][suspect] = new_loc
        state["pending_bonus"] = None
        state["phase"] = "POST_MOVE"

        events.append(
            DomainEvent(
                type="TOKEN_MOVED",
                visibility="public",
                payload={"suspect": suspect, "from": prev_loc, "to": new_loc, "reason": "bonus_teleport"},
            )
        )
        events.append(
            DomainEvent(
                type="BONUS_EFFECT_RESOLVED",
                visibility="public",
                payload={"player": player_id, "card_id": pb["card_id"], "effect": pb["effect"]},
            )
        )

    def _handle_bonus_choose_target(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"BONUS_RESOLVE"})
        pb = state["pending_bonus"]
        if pb is None or pb["step"] != "CHOOSE_TARGET":
            raise RuleError("INVALID_BONUS_STEP", "Not awaiting target selection.")

        player_id = action["player"]
        target = action.get("target_player")
        if target not in state["players"] or target == player_id:
            raise RuleError("INVALID_TARGET", f"Invalid target player: {target!r}")

        effect = pb["effect"]
        if effect == "swap_position":
            s_a = state["players"][player_id]["suspect"]
            s_b = state["players"][target]["suspect"]
            loc_a = copy.deepcopy(state["tokens"][s_a])
            loc_b = copy.deepcopy(state["tokens"][s_b])
            state["tokens"][s_a] = loc_b
            state["tokens"][s_b] = loc_a
            state["pending_bonus"] = None
            state["phase"] = "POST_MOVE"

            events.append(
                DomainEvent(
                    type="POSITIONS_SWAPPED",
                    visibility="public",
                    payload={"player_a": player_id, "player_b": target},
                )
            )
            events.append(
                DomainEvent(
                    type="TOKEN_MOVED",
                    visibility="public",
                    payload={"suspect": s_a, "from": loc_a, "to": loc_b, "reason": "bonus_swap"},
                )
            )
            events.append(
                DomainEvent(
                    type="TOKEN_MOVED",
                    visibility="public",
                    payload={"suspect": s_b, "from": loc_b, "to": loc_a, "reason": "bonus_swap"},
                )
            )
            events.append(
                DomainEvent(
                    type="BONUS_EFFECT_RESOLVED",
                    visibility="public",
                    payload={"player": player_id, "card_id": pb["card_id"], "effect": effect},
                )
            )
        else:
            if not state["players"][target]["hand"]:
                state["pending_bonus"] = None
                state["phase"] = "POST_MOVE"
                events.append(
                    DomainEvent(
                        type="BONUS_EFFECT_RESOLVED",
                        visibility="public",
                        payload={"player": player_id, "card_id": pb["card_id"], "effect": effect},
                    )
                )
            else:
                pb["target_player"] = target
                pb["step"] = "RESPOND_CARD"

    def _handle_bonus_respond_card(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"BONUS_RESOLVE"})
        pb = state["pending_bonus"]
        if pb is None or pb["step"] != "RESPOND_CARD":
            raise RuleError("INVALID_BONUS_STEP", "Not awaiting card response.")

        responder = action["player"]
        card = action.get("card")
        if card not in state["players"][responder]["hand"]:
            raise RuleError("CARD_NOT_IN_HAND", f"Card {card!r} is not in {responder!r}'s hand.")

        drawer = pb["drawer"]
        effect = pb["effect"]

        if effect in ("peek_opponent_card", "peek_left_card"):
            events.append(
                DomainEvent(
                    type="BONUS_CARD_PEEKED",
                    visibility="private",
                    recipients=(drawer, responder),
                    payload={"drawer": drawer, "from_player": responder, "card": card},
                )
            )
        elif effect == "force_public_reveal":
            state["public_revealed_cards"].append({"owner": responder, "card": card})
            events.append(
                DomainEvent(
                    type="CARD_REVEALED_PUBLICLY",
                    visibility="public",
                    payload={"owner": responder, "card": card, "triggered_by": drawer},
                )
            )

        state["pending_bonus"] = None
        state["phase"] = "POST_MOVE"
        events.append(
            DomainEvent(
                type="BONUS_EFFECT_RESOLVED",
                visibility="public",
                payload={"player": drawer, "card_id": pb["card_id"], "effect": effect},
            )
        )

    def _handle_bonus_make_suggestion(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"BONUS_RESOLVE"})
        pb = state["pending_bonus"]
        if pb is None or pb["step"] != "CHOOSE_SUGGESTION":
            raise RuleError("INVALID_BONUS_STEP", "Not awaiting bonus suggestion.")

        room = action.get("room")
        if room not in self.data.rooms:
            raise RuleError("INVALID_ROOM", f"Unknown room: {room!r}")

        state["pending_bonus"] = None
        events.append(
            DomainEvent(
                type="BONUS_EFFECT_RESOLVED",
                visibility="public",
                payload={"player": action["player"], "card_id": pb["card_id"], "effect": pb["effect"]},
            )
        )
        self._start_suggestion(
            state,
            suggester=action["player"],
            suspect=action.get("suspect"),
            weapon=action.get("weapon"),
            room=room,
            from_bonus_card=True,
            events=events,
        )

    def _handle_make_suggestion(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"POST_MOVE"})
        player_id = action["player"]
        loc = state["tokens"][state["players"][player_id]["suspect"]]
        if loc["kind"] != "room":
            raise RuleError("NOT_IN_ROOM", "Must be inside a room to make a suggestion.")

        self._start_suggestion(
            state,
            suggester=player_id,
            suspect=action.get("suspect"),
            weapon=action.get("weapon"),
            room=loc["room"],
            from_bonus_card=False,
            events=events,
        )

    def _start_suggestion(
        self,
        state: GameState,
        suggester: str,
        suspect: Any,
        weapon: Any,
        room: str,
        from_bonus_card: bool,
        events: list[DomainEvent],
    ) -> None:
        if suspect not in self.data.suspects or weapon not in self.data.weapons:
            raise RuleError("INVALID_CARD", "Suggestion must specify valid suspect and weapon.")

        prev_loc = state["tokens"][suspect]
        new_loc = {"kind": "room", "room": room}
        state["tokens"][suspect] = new_loc
        state["weapons"][weapon] = room

        if prev_loc != new_loc:
            events.append(
                DomainEvent(
                    type="TOKEN_MOVED",
                    visibility="public",
                    payload={"suspect": suspect, "from": prev_loc, "to": new_loc, "reason": "suggestion_pull"},
                )
            )

        for pid, pstate in state["players"].items():
            if pstate["suspect"] == suspect and pid != suggester:
                pstate["pulled_into_room"] = True

        events.append(
            DomainEvent(
                type="SUGGESTION_MADE",
                visibility="public",
                payload={
                    "suggester": suggester,
                    "suspect": suspect,
                    "weapon": weapon,
                    "room": room,
                    "from_bonus_card": from_bonus_card,
                },
            )
        )

        idx = state["turn_order"].index(suggester)
        n = len(state["turn_order"])
        responder_queue = [state["turn_order"][(idx + offset) % n] for offset in range(1, n)]

        state["pending_suggestion"] = {
            "suggester": suggester,
            "suspect": suspect,
            "weapon": weapon,
            "room": room,
            "responder_queue": responder_queue,
            "current_responder_index": 0,
            "from_bonus_card": from_bonus_card,
        }
        state["phase"] = "DISPROVE"

    def _handle_show_disprove_card(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"DISPROVE"})
        ps = state["pending_suggestion"]
        assert ps is not None
        responder = action["player"]
        card = action.get("card")
        needed = {ps["suspect"], ps["weapon"], ps["room"]}

        if card not in needed or card not in state["players"][responder]["hand"]:
            raise RuleError("INVALID_DISPROVE_CARD", f"Card {card!r} cannot disprove this suggestion.")

        suggester = ps["suggester"]
        state["pending_suggestion"] = None
        state["phase"] = "POST_SUGGESTION"

        events.append(
            DomainEvent(
                type="SUGGESTION_DISPROVED",
                visibility="public",
                payload={"suggester": suggester, "disprover": responder},
            )
        )
        events.append(
            DomainEvent(
                type="CARD_SHOWN_PRIVATELY",
                visibility="private",
                recipients=(suggester, responder),
                payload={"from_player": responder, "to_player": suggester, "card": card},
            )
        )

    def _handle_pass_disprove(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"DISPROVE"})
        ps = state["pending_suggestion"]
        assert ps is not None
        responder = action["player"]
        needed = {ps["suspect"], ps["weapon"], ps["room"]}

        if any(c in needed for c in state["players"][responder]["hand"]):
            raise RuleError("MUST_DISPROVE", "You hold a matching card and must show one.")

        events.append(
            DomainEvent(
                type="DISPROVE_PASSED",
                visibility="public",
                payload={"player": responder},
            )
        )

        next_idx = ps["current_responder_index"] + 1
        if next_idx < len(ps["responder_queue"]):
            ps["current_responder_index"] = next_idx
        else:
            suggester = ps["suggester"]
            state["pending_suggestion"] = None
            state["phase"] = "POST_SUGGESTION"
            events.append(
                DomainEvent(
                    type="SUGGESTION_UNDISPROVED",
                    visibility="public",
                    payload={"suggester": suggester},
                )
            )

    def _handle_make_accusation(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        self._require_phase(state, {"TURN_START", "POST_MOVE", "POST_SUGGESTION"})
        player_id = action["player"]
        suspect = action.get("suspect")
        weapon = action.get("weapon")
        room = action.get("room")

        if suspect not in self.data.suspects or weapon not in self.data.weapons or room not in self.data.rooms:
            raise RuleError("INVALID_CARD", "Accusation must specify valid suspect, weapon, and room.")

        if not self._can_accuse(state, player_id):
            raise RuleError("NOT_IN_ROOM", "Must be inside a room to make an accusation under current config.")

        env = state["envelope"]
        correct = (suspect == env["suspect"] and weapon == env["weapon"] and room == env["room"])

        events.append(
            DomainEvent(
                type="ACCUSATION_MADE",
                visibility="public",
                payload={
                    "player": player_id,
                    "suspect": suspect,
                    "weapon": weapon,
                    "room": room,
                    "correct": correct,
                },
            )
        )

        if correct:
            state["phase"] = "GAME_OVER"
            state["outcome"] = {
                "winner": player_id,
                "reason": "CORRECT_ACCUSATION",
                "envelope": copy.deepcopy(env),
            }
            events.append(
                DomainEvent(
                    type="GAME_ENDED",
                    visibility="public",
                    payload=copy.deepcopy(state["outcome"]),
                )
            )
            return

        state["players"][player_id]["eliminated"] = True
        state["extra_turn_pending"] = False
        events.append(
            DomainEvent(
                type="PLAYER_ELIMINATED",
                visibility="public",
                payload={"player": player_id},
            )
        )

        alive = [pid for pid in state["turn_order"] if not state["players"][pid]["eliminated"]]
        if not alive:
            state["phase"] = "GAME_OVER"
            state["outcome"] = {
                "winner": None,
                "reason": "ALL_ELIMINATED",
                "envelope": copy.deepcopy(env),
            }
            events.append(
                DomainEvent(
                    type="GAME_ENDED",
                    visibility="public",
                    payload=copy.deepcopy(state["outcome"]),
                )
            )
            return

        self._advance_turn(state, events)

    def _handle_end_turn(self, state: GameState, action: Action, events: list[DomainEvent]) -> None:
        if state["phase"] in ("MOVE", "BONUS_MOVE"):
            suspect = state["players"][action["player"]]["suspect"]
            hallways, rooms = self._reachable_destinations(state, suspect, state["movement_remaining"])
            if hallways or rooms:
                raise RuleError("INVALID_PHASE", "Cannot end turn while legal movement destinations exist.")
        else:
            self._require_phase(state, {"POST_MOVE", "POST_SUGGESTION"})

        self._advance_turn(state, events)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _require_phase(self, state: GameState, allowed: set[str]) -> None:
        if state["phase"] not in allowed:
            raise RuleError(
                "INVALID_PHASE",
                f"Action not allowed in phase {state['phase']!r}; allowed: {sorted(allowed)}",
            )

    def _expected_actor(self, state: GameState) -> str:
        phase = state["phase"]
        if phase == "DISPROVE":
            ps = state["pending_suggestion"]
            assert ps is not None
            return ps["responder_queue"][ps["current_responder_index"]]
        if phase == "BONUS_RESOLVE":
            pb = state["pending_bonus"]
            assert pb is not None
            if pb["step"] == "RESPOND_CARD":
                assert pb["target_player"] is not None
                return pb["target_player"]
            return pb["drawer"]
        return state["turn_order"][state["current_player_index"]]

    def _can_accuse(self, state: GameState, player_id: str) -> bool:
        if not state["config"].get("accusation_requires_room", False):
            return True
        loc = state["tokens"][state["players"][player_id]["suspect"]]
        return loc["kind"] == "room"

    def _advance_turn(self, state: GameState, events: list[DomainEvent]) -> None:
        current_player = state["turn_order"][state["current_player_index"]]
        extra = bool(state["extra_turn_pending"] and not state["players"][current_player]["eliminated"])

        events.append(
            DomainEvent(
                type="TURN_ENDED",
                visibility="public",
                payload={"player": current_player, "extra_turn": extra},
            )
        )

        if extra:
            state["extra_turn_pending"] = False
            next_idx = state["current_player_index"]
        else:
            n = len(state["turn_order"])
            next_idx = state["current_player_index"]
            for offset in range(1, n + 1):
                cand = (state["current_player_index"] + offset) % n
                if not state["players"][state["turn_order"][cand]]["eliminated"]:
                    next_idx = cand
                    break

        state["current_player_index"] = next_idx
        state["turn_number"] += 1
        state["phase"] = "TURN_START"
        state["dice"] = None
        state["movement_remaining"] = 0

        events.append(
            DomainEvent(
                type="TURN_STARTED",
                visibility="public",
                payload={"player": state["turn_order"][next_idx], "turn_number": state["turn_number"]},
            )
        )

    def _occupied_hallways(self, state: GameState, exclude_suspect: str) -> set[tuple[int, int]]:
        occupied: set[tuple[int, int]] = set()
        for suspect, loc in state["tokens"].items():
            if suspect != exclude_suspect and loc["kind"] == "hallway":
                occupied.add((loc["x"], loc["y"]))
        return occupied

    def _reachable_destinations(
        self, state: GameState, suspect: str, max_steps: int
    ) -> tuple[set[tuple[int, int]], set[str]]:
        if max_steps <= 0:
            return set(), set()

        occupied = self._occupied_hallways(state, exclude_suspect=suspect)
        loc = state["tokens"][suspect]

        queue: deque[tuple[tuple[int, int], int]] = deque()
        dist_map: dict[tuple[int, int], int] = {}
        start_room: str | None = None

        if loc["kind"] == "hallway":
            start_pos = (loc["x"], loc["y"])
            dist_map[start_pos] = 0
            queue.append((start_pos, 0))
        else:
            start_room = loc["room"]
            for door in self.data.room_doorways[start_room]:
                if door not in occupied:
                    dist_map[door] = 1
                    queue.append((door, 1))

        while queue:
            (cx, cy), d = queue.popleft()
            if d >= max_steps:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (cx + dx, cy + dy)
                if nxt in self.data.walkable and nxt not in occupied and nxt not in dist_map:
                    dist_map[nxt] = d + 1
                    queue.append((nxt, d + 1))

        reachable_hallways = {pos for pos, d in dist_map.items() if 1 <= d <= max_steps}
        reachable_rooms: set[str] = set()
        for room, doors in self.data.room_doorways.items():
            if room == start_room:
                continue
            for door in doors:
                if door in dist_map and dist_map[door] + 1 <= max_steps:
                    reachable_rooms.add(room)
                    break

        return reachable_hallways, reachable_rooms
