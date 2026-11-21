"""Gymnasium-based strategy & winning-formula study for Clue (Classic + '?' Bonus Cards)."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from games.clue.reference.engine import ClueEngine  # noqa: E402

engine = ClueEngine()


class SmartNotebook:
    """Strictly fair Clue notebook fed ONLY by legally visible domain events.
    Supports optional `use_constraint_propagation` (tracking passes & disjunctive clauses).
    """

    def __init__(self, pid: str, use_constraints: bool = True) -> None:
        self.pid = pid
        self.use_constraints = use_constraints
        self.suspects = set(engine.data.suspects)
        self.weapons = set(engine.data.weapons)
        self.rooms = set(engine.data.rooms)
        self.own_hand: set[str] = set()
        self.known_owner: dict[str, str] = {}
        self.player_lacks: dict[str, set[str]] = defaultdict(set)
        self.clauses: list[tuple[str, set[str]]] = []  # (player_id, possible cards they hold >=1 of)
        self._last_sug: tuple[str, str, str, str] | None = None

    def _elim(self, card: str, owner: str) -> None:
        self.suspects.discard(card)
        self.weapons.discard(card)
        self.rooms.discard(card)
        self.known_owner[card] = owner

    def observe(self, ev: dict) -> None:
        vis = ev["visibility"]
        if vis == "hidden" or (vis == "private" and self.pid not in ev.get("recipients", [])):
            return
        et = ev["type"]
        pl = ev["payload"]

        if et == "CARDS_DEALT" and pl["player"] == self.pid:
            for c in pl["cards"]:
                self.own_hand.add(c)
                self._elim(c, self.pid)
        elif et == "CARD_SHOWN_PRIVATELY":
            self._elim(pl["card"], pl["from_player"])
        elif et == "BONUS_CARD_PEEKED":
            self._elim(pl["card"], pl["from_player"])
        elif et == "CARD_REVEALED_PUBLICLY":
            self._elim(pl["card"], pl["owner"])
        elif et == "SUGGESTION_MADE":
            self._last_sug = (pl["suggester"], pl["suspect"], pl["weapon"], pl["room"])
        elif et == "DISPROVE_PASSED" and self._last_sug and self.use_constraints:
            _, s, w, r = self._last_sug
            self.player_lacks[pl["player"]].update((s, w, r))
        elif et == "SUGGESTION_DISPROVED" and self._last_sug and self.use_constraints:
            _, s, w, r = self._last_sug
            self.clauses.append((pl["disprover"], {s, w, r}))
        elif et == "SUGGESTION_UNDISPROVED" and self._last_sug:
            suggester, s, w, r = self._last_sug
            if suggester == self.pid:
                if s not in self.own_hand:
                    self.suspects = {s}
                if w not in self.own_hand:
                    self.weapons = {w}
                if r not in self.own_hand:
                    self.rooms = {r}

        if self.use_constraints:
            self._propagate()

    def _propagate(self) -> None:
        changed = True
        while changed:
            changed = False
            new_clauses = []
            for owner, cards in self.clauses:
                if any(self.known_owner.get(c) == owner for c in cards):
                    continue  # already satisfied
                filtered = {
                    c
                    for c in cards
                    if c not in self.player_lacks[owner]
                    and (c not in self.known_owner or self.known_owner[c] == owner)
                }
                if len(filtered) == 1:
                    sole = next(iter(filtered))
                    if sole not in self.known_owner:
                        self._elim(sole, owner)
                        changed = True
                elif filtered:
                    new_clauses.append((owner, filtered))
            self.clauses = new_clauses

            # Check if ALL 3 other players lack a card (and I don't hold it) => 100% in envelope!
            for pool_name, pool in (("suspects", self.suspects), ("weapons", self.weapons), ("rooms", self.rooms)):
                if len(pool) > 1:
                    for c in list(pool):
                        if c not in self.own_hand and len(
                            [p for p, lacks in self.player_lacks.items() if p != self.pid and c in lacks]
                        ) >= 3:
                            if pool_name == "suspects":
                                self.suspects = {c}
                            elif pool_name == "weapons":
                                self.weapons = {c}
                            else:
                                self.rooms = {c}
                            changed = True
                            break

    def unknowns_count(self) -> int:
        return len(self.suspects) + len(self.weapons) + len(self.rooms)

    def is_solved(self) -> bool:
        return len(self.suspects) == 1 and len(self.weapons) == 1 and len(self.rooms) == 1

    def solution(self) -> tuple[str, str, str]:
        return (sorted(self.suspects)[0], sorted(self.weapons)[0], sorted(self.rooms)[0])


def choose_clue_action(strategy: str, state: dict, actor: str, nb: SmartNotebook) -> dict:
    view = engine.get_player_view(state, actor)
    legal = engine.get_legal_actions(state, actor)
    lt = {a["type"] for a in legal}
    phase = view["phase"]

    # Always accuse immediately when 100% solved
    if nb.is_solved() and "MAKE_ACCUSATION" in lt:
        s, w, r = nb.solution()
        return {"type": "MAKE_ACCUSATION", "player": actor, "suspect": s, "weapon": w, "room": r}

    # Resolve situational strategy
    mode = strategy
    if strategy == "situational":
        if nb.unknowns_count() <= 6:
            mode = "bluff_isolate"
        elif nb.unknowns_count() >= 13:
            mode = "bonus_hunter"
        else:
            mode = "pure_unknown"

    if phase == "TURN_START":
        loc = view["tokens"][view["players"][actor]["suspect"]]
        if "STAY_FOR_SUGGESTION" in lt and loc["kind"] == "room" and (loc["room"] in nb.rooms or mode == "bluff_isolate"):
            return {"type": "STAY_FOR_SUGGESTION", "player": actor}
        if "USE_SECRET_PASSAGE" in lt and loc["kind"] == "room":
            dest = engine.data.secret_passages[loc["room"]]
            if dest in nb.rooms:
                return {"type": "USE_SECRET_PASSAGE", "player": actor}
        return {"type": "ROLL_DICE", "player": actor}

    if phase in ("MOVE", "BONUS_MOVE"):
        rm = [a for a in legal if a["type"] == "MOVE_TO_ROOM"]
        hm = [a for a in legal if a["type"] == "MOVE_TO_HALLWAY"]
        qm = [a for a in hm if phase == "MOVE" and (a["x"], a["y"]) in engine.data.question_marks]
        urm = [a for a in rm if a["room"] in nb.rooms]

        if mode == "bonus_hunter" and qm:
            return qm[0]
        if urm:
            return urm[0]
        if qm and mode != "pure_unknown":
            return qm[0]
        if rm:
            return rm[0]
        if hm:
            target_rooms = sorted(nb.rooms) if nb.rooms else engine.data.rooms
            doors = [d for r in target_rooms for d in engine.data.room_doorways[r]]
            return min(hm, key=lambda a: min(abs(a["x"] - dx) + abs(a["y"] - dy) for dx, dy in doors))
        return {"type": "END_TURN", "player": actor}

    if phase == "BONUS_RESOLVE":
        pb = view["pending_bonus"]
        if pb["step"] == "CHOOSE_ROOM":
            room = sorted(nb.rooms)[0] if nb.rooms else engine.data.rooms[0]
            return {"type": "BONUS_CHOOSE_ROOM", "player": actor, "room": room}
        if pb["step"] == "CHOOSE_TARGET":
            # Prefer player furthest clockwise (hardest to extract via suggestions)
            order = view["turn_order"]
            idx = order.index(actor)
            pref = order[(idx - 1) % len(order)]
            return next((a for a in legal if a["target_player"] == pref), legal[0])
        if pb["step"] == "RESPOND_CARD":
            return legal[0]
        if pb["step"] == "CHOOSE_SUGGESTION":
            s = sorted(nb.suspects)[0]
            w = sorted(nb.weapons)[0]
            r = sorted(nb.rooms)[0]
            return {"type": "BONUS_MAKE_SUGGESTION", "player": actor, "suspect": s, "weapon": w, "room": r}

    if phase == "POST_MOVE":
        if "MAKE_SUGGESTION" in lt:
            cur_room = view["tokens"][view["players"][actor]["suspect"]]["room"]
            own_s = [c for c in nb.own_hand if c in engine.data.suspects]
            own_w = [c for c in nb.own_hand if c in engine.data.weapons]
            if mode == "bluff_isolate":
                # Isolate 1-2 unknowns by mixing in own-hand card when a category is already solved or narrowed
                s = own_s[0] if (len(nb.suspects) == 1 and own_s) else sorted(nb.suspects)[0]
                w = own_w[0] if (len(nb.weapons) == 1 and own_w) else sorted(nb.weapons)[0]
                if len(nb.suspects) > 1 and len(nb.weapons) > 1 and cur_room in nb.rooms and own_s:
                    s = own_s[0]
            else:
                s = sorted(nb.suspects)[0]
                w = sorted(nb.weapons)[0]
            return {"type": "MAKE_SUGGESTION", "player": actor, "suspect": s, "weapon": w}
        return {"type": "END_TURN", "player": actor}

    if phase == "DISPROVE":
        # Prefer showing room card over suspect/weapon (least narrowing)
        room_opts = [a for a in legal if a.get("card") in engine.data.rooms]
        return room_opts[0] if room_opts else legal[0]

    return {"type": "END_TURN", "player": actor}


CLUE_MODES = ["pure_unknown", "bluff_isolate", "bonus_hunter"]


class ClueStrategyEnv(gym.Env):
    """Gymnasium Env where p1 chooses a Clue strategy mode per turn against 3 constraint-tracking opponents."""

    metadata = {"render_modes": []}

    def __init__(self, opp_strategies: list[str]) -> None:
        super().__init__()
        self.opp_strategies = opp_strategies
        # Obs: (unknowns_bucket: 0..3, in_room: 0..1, turn_bucket: 0..2)
        self.observation_space = spaces.MultiDiscrete([4, 2, 3])
        self.action_space = spaces.Discrete(len(CLUE_MODES))
        self.state: dict[str, Any] = {}
        self.notebooks: dict[str, SmartNotebook] = {}
        self._seed_counter = 3000

    def _broadcast(self, events: list[dict]) -> None:
        for ev in events:
            for nb in self.notebooks.values():
                nb.observe(ev)

    def _obs(self) -> np.ndarray:
        nb = self.notebooks["p1"]
        u = nb.unknowns_count()
        u_b = 0 if u <= 5 else (1 if u <= 9 else (2 if u <= 13 else 3))
        in_room = 1 if self.state["tokens"]["scarlett"]["kind"] == "room" else 0
        t = self.state["turn_number"]
        t_b = 0 if t <= 12 else (1 if t <= 28 else 2)
        return np.array([u_b, in_room, t_b], dtype=np.int64)

    def _run_until_p1_turn_start(self) -> None:
        for _ in range(120):
            if engine.get_outcome(self.state) is not None:
                return
            actors = [pid for pid in self.state["turn_order"] if engine.get_legal_actions(self.state, pid)]
            if not actors:
                return
            actor = actors[0]
            if actor == "p1" and self.state["phase"] == "TURN_START":
                return
            if actor == "p1":
                act = choose_clue_action("pure_unknown", self.state, "p1", self.notebooks["p1"])
            else:
                idx = self.state["turn_order"].index(actor) - 1
                act = choose_clue_action(self.opp_strategies[idx], self.state, actor, self.notebooks[actor])
            res = engine.apply_action(self.state, act)
            self.state = res.state
            self._broadcast(res.events_as_dicts())

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        s = seed if seed is not None else self._seed_counter
        self._seed_counter += 1
        step = engine.setup(
            {
                "players": [
                    {"id": "p1", "suspect": "scarlett"},
                    {"id": "p2", "suspect": "mustard"},
                    {"id": "p3", "suspect": "white"},
                    {"id": "p4", "suspect": "green"},
                ],
                "enable_bonus_cards": True,
            },
            seed=s,
        )
        self.state = step.state
        self.notebooks = {pid: SmartNotebook(pid, use_constraints=True) for pid in self.state["turn_order"]}
        self._broadcast(step.events_as_dicts())
        self._run_until_p1_turn_start()
        return self._obs(), {}

    def step(self, action: int):
        mode = CLUE_MODES[int(action)]
        prev_u = self.notebooks["p1"].unknowns_count()

        # Execute p1's full turn under chosen mode
        cur_turn = self.state["turn_number"]
        for _ in range(25):
            if engine.get_outcome(self.state) is not None or self.state["turn_number"] != cur_turn:
                break
            actors = [pid for pid in self.state["turn_order"] if engine.get_legal_actions(self.state, pid)]
            if not actors:
                break
            actor = actors[0]
            if actor == "p1":
                act = choose_clue_action(mode, self.state, "p1", self.notebooks["p1"])
            else:
                idx = self.state["turn_order"].index(actor) - 1
                act = choose_clue_action(self.opp_strategies[idx], self.state, actor, self.notebooks[actor])
            res = engine.apply_action(self.state, act)
            self.state = res.state
            self._broadcast(res.events_as_dicts())

        self._run_until_p1_turn_start()
        outcome = engine.get_outcome(self.state)
        terminated = outcome is not None
        truncated = self.state["turn_number"] > 120

        reward = (prev_u - self.notebooks["p1"].unknowns_count()) * 0.05
        if terminated:
            reward += 1.0 if outcome["winner"] == "p1" else -1.0

        return self._obs(), float(reward), terminated, truncated, {"outcome": outcome}


def run_clue_study() -> dict[str, Any]:
    # 1) Benchmark: Simple Notebook (no pass tracking) vs Constraint-Tracking Consistent vs Situational
    profiles = [
        ("naive_no_pass_tracking", "pure_unknown", False),
        ("consistent_pure_unknown", "pure_unknown", True),
        ("consistent_bluff_isolate", "bluff_isolate", True),
        ("situational_adaptive", "situational", True),
    ]
    wins = defaultdict(int)
    turns_list = []
    n_games = 160
    suspects = ["scarlett", "mustard", "white", "green"]

    for g in range(n_games):
        rot = profiles[g % 4 :] + profiles[: g % 4]
        pids = ["p1", "p2", "p3", "p4"]
        step = engine.setup(
            {"players": [{"id": pids[i], "suspect": suspects[i]} for i in range(4)], "enable_bonus_cards": True},
            seed=11000 + g,
        )
        state = step.state
        nbs = {pids[i]: SmartNotebook(pids[i], use_constraints=rot[i][2]) for i in range(4)}
        strats = {pids[i]: rot[i][1] for i in range(4)}
        names = {pids[i]: rot[i][0] for i in range(4)}
        for ev in step.events_as_dicts():
            for nb in nbs.values():
                nb.observe(ev)

        for _ in range(500):
            if engine.get_outcome(state) is not None:
                break
            actor = [pid for pid in state["turn_order"] if engine.get_legal_actions(state, pid)][0]
            act = choose_clue_action(strats[actor], state, actor, nbs[actor])
            res = engine.apply_action(state, act)
            state = res.state
            for ev in res.events_as_dicts():
                for nb in nbs.values():
                    nb.observe(ev)

        out = engine.get_outcome(state)
        if out and out["winner"]:
            wins[names[out["winner"]]] += 1
            turns_list.append(state["turn_number"])

    # 2) Compare bonus_hunter vs pure_unknown vs bluff_isolate vs situational (all with constraint tracking!)
    profiles2 = [
        ("consistent_bonus_hunter", "bonus_hunter", True),
        ("consistent_pure_unknown", "pure_unknown", True),
        ("consistent_bluff_isolate", "bluff_isolate", True),
        ("situational_adaptive", "situational", True),
    ]
    wins2 = defaultdict(int)
    for g in range(160):
        rot = profiles2[g % 4 :] + profiles2[: g % 4]
        pids = ["p1", "p2", "p3", "p4"]
        step = engine.setup(
            {"players": [{"id": pids[i], "suspect": suspects[i]} for i in range(4)], "enable_bonus_cards": True},
            seed=15000 + g,
        )
        state = step.state
        nbs = {pids[i]: SmartNotebook(pids[i], use_constraints=True) for i in range(4)}
        strats = {pids[i]: rot[i][1] for i in range(4)}
        names = {pids[i]: rot[i][0] for i in range(4)}
        for ev in step.events_as_dicts():
            for nb in nbs.values():
                nb.observe(ev)

        for _ in range(500):
            if engine.get_outcome(state) is not None:
                break
            actor = [pid for pid in state["turn_order"] if engine.get_legal_actions(state, pid)][0]
            act = choose_clue_action(strats[actor], state, actor, nbs[actor])
            res = engine.apply_action(state, act)
            state = res.state
            for ev in res.events_as_dicts():
                for nb in nbs.values():
                    nb.observe(ev)

        out = engine.get_outcome(state)
        if out and out["winner"]:
            wins2[names[out["winner"]]] += 1

    # 3) Gymnasium Q-Learning on ClueStrategyEnv (250 episodes) + Eval (100 episodes)
    env = ClueStrategyEnv(opp_strategies=["pure_unknown", "bluff_isolate", "bonus_hunter"])
    Q = np.zeros((4, 2, 3, len(CLUE_MODES)), dtype=np.float64)
    rng = np.random.default_rng(42)

    for ep in range(250):
        eps = max(0.08, 0.45 * (1.0 - ep / 250.0))
        obs, _ = env.reset(seed=30000 + ep)
        done = False
        while not done:
            key = tuple(obs)
            act = int(rng.integers(0, len(CLUE_MODES))) if rng.random() < eps else int(np.argmax(Q[key]))
            nxt, rew, term, trunc, _ = env.step(act)
            done = term or trunc
            target = rew if done else rew + 0.95 * float(np.max(Q[tuple(nxt)]))
            Q[key][act] += 0.15 * (target - Q[key][act])
            obs = nxt

    q_wins = 0
    for ep in range(100):
        obs, _ = env.reset(seed=40000 + ep)
        done = False
        while not done:
            act = int(np.argmax(Q[tuple(obs)]))
            obs, _, term, trunc, info = env.step(act)
            done = term or trunc
        if info["outcome"] and info["outcome"]["winner"] == "p1":
            q_wins += 1

    bucket_names = ["endgame(<=5 unknowns)", "late(6-9 unknowns)", "mid(10-13 unknowns)", "early(14+ unknowns)"]
    phase_prefs = {}
    for b, name in enumerate(bucket_names):
        sub_q = Q[b].mean(axis=(0, 1))
        best_idx = int(np.argmax(sub_q))
        phase_prefs[name] = {
            "best_mode": CLUE_MODES[best_idx],
            "q_values": {CLUE_MODES[i]: round(float(sub_q[i]), 3) for i in range(len(CLUE_MODES))},
        }

    return {
        "benchmark_1_constraint_impact_pct": {p[0]: round(100.0 * wins[p[0]] / n_games, 1) for p in profiles},
        "benchmark_1_avg_turns": round(float(np.mean(turns_list)), 1),
        "benchmark_2_all_constraint_pct": {p[0]: round(100.0 * wins2[p[0]] / 160, 1) for p in profiles2},
        "gym_qlearning_win_rate_pct": round(100.0 * q_wins / 100, 1),
        "gym_qlearning_unknowns_policy": phase_prefs,
    }


if __name__ == "__main__":
    print(json.dumps(run_clue_study(), indent=2, ensure_ascii=False))
