"""Gymnasium-based strategy & winning-formula study for Splendor."""

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

from games.splendor.reference.engine import SplendorEngine  # noqa: E402

engine = SplendorEngine()
GEMS = engine.data.gems


def _shortfall(pstate: dict, card_id: str) -> dict[str, int]:
    card = engine.data.cards[card_id]
    return {
        g: max(0, card["cost"].get(g, 0) - pstate["bonuses"][g] - pstate["tokens"][g])
        for g in GEMS
    }


def _net_deficit(pstate: dict, card_id: str) -> int:
    sf = _shortfall(pstate, card_id)
    return max(0, sum(sf.values()) - pstate["tokens"]["gold"])


def _noble_color_weights(view: dict, pstate: dict) -> dict[str, float]:
    weights = {g: 0.0 for g in GEMS}
    for nid in view["nobles"]:
        req = engine.data.nobles[nid]["requirements"]
        missing = sum(max(0, r - pstate["bonuses"][g]) for g, r in req.items())
        if missing == 0:
            continue
        inv = 1.0 / missing
        for g, r in req.items():
            if pstate["bonuses"][g] < r:
                weights[g] += inv
    return weights


def _discard_action(actor: str, pstate: dict, keep_needs: dict[str, int]) -> dict:
    excess = sum(pstate["tokens"].values()) - 10
    order = sorted(GEMS, key=lambda g: (keep_needs.get(g, 0), pstate["tokens"][g])) + ["gold"]
    discard: dict[str, int] = {}
    rem = excess
    for tok in order:
        if rem <= 0:
            break
        take = min(pstate["tokens"][tok], rem)
        if take > 0:
            discard[tok] = take
            rem -= take
    return {"type": "DISCARD_TOKENS", "player": actor, "tokens": discard}


def _take_gems_for_target(actor: str, legal: list[dict], needs: dict[str, int], bank: dict[str, int]) -> dict:
    take3 = [a for a in legal if a["type"] == "TAKE_THREE_GEMS"]
    take2 = [a for a in legal if a["type"] == "TAKE_TWO_SAME_GEM"]

    best_t2 = None
    best_t2_score = -1.0
    for a in take2:
        g = a["gem"]
        if needs.get(g, 0) >= 2:
            sc = 2.6 + (0.2 if bank[g] == 4 else 0.0)
            if sc > best_t2_score:
                best_t2_score = sc
                best_t2 = a

    best_t3 = None
    best_t3_score = -1.0
    for a in take3:
        sc = sum(1.0 if needs.get(g, 0) > 0 else 0.15 for g in a["gems"])
        if sc > best_t3_score:
            best_t3_score = sc
            best_t3 = a

    if best_t2 is not None and best_t2_score >= best_t3_score:
        return best_t2
    if best_t3 is not None:
        return best_t3
    if take2:
        return take2[0]
    return legal[0]


def choose_splendor_action(strategy: str, state: dict, actor: str) -> dict:
    """Execute one of 5 named strategies using ONLY legal view + legal actions."""
    view = engine.get_player_view(state, actor)
    pstate = view["players"][actor]
    legal = engine.get_legal_actions(state, actor)
    phase = view["phase"]

    if phase == "CHOOSE_NOBLE":
        return legal[0]

    visible_cards = [cid for t in ("1", "2", "3") for cid in view["market"][t]] + [
        e["card_id"] for e in pstate["reserved"]
    ]
    nweights = _noble_color_weights(view, pstate)
    my_pts = pstate["points"]
    max_opp_pts = max(pv["points"] for pid, pv in view["players"].items() if pid != actor)
    engine_size = sum(pstate["bonuses"].values())

    # Resolve situational strategy into a concrete mode
    mode = strategy
    if strategy == "situational":
        if my_pts >= 10 or max_opp_pts >= 11:
            mode = "points_rush"
        elif engine_size < 4:
            mode = "engine_build"
        elif max(nweights.values(), default=0.0) >= 0.45:
            mode = "noble_focus"
        else:
            mode = "points_rush"

    if phase == "DISCARD_TOKENS":
        target = min(visible_cards, key=lambda c: _net_deficit(pstate, c))
        return _discard_action(actor, pstate, _shortfall(pstate, target))

    buys = [a for a in legal if a["type"] == "BUY_CARD"]
    reserves_market = [a for a in legal if a["type"] == "RESERVE_CARD" and a["source"] == "market"]

    # Always buy immediately if a card wins or triggers >=15 pts!
    for a in buys:
        if my_pts + engine.data.cards[a["card_id"]]["points"] >= view["config"]["target_points"]:
            return a

    if mode == "engine_build":
        if buys:
            return max(
                buys,
                key=lambda a: (
                    engine.data.cards[a["card_id"]]["points"] * 1.5
                    + nweights[engine.data.cards[a["card_id"]]["bonus"]] * 1.2
                    - sum(engine.data.cards[a["card_id"]]["cost"].values()) * 0.4
                ),
            )
        t12 = [cid for t in ("1", "2") for cid in view["market"][t]] or visible_cards
        target = min(
            t12,
            key=lambda c: (
                _net_deficit(pstate, c)
                - nweights[engine.data.cards[c]["bonus"]] * 0.8
                - engine.data.cards[c]["points"] * 0.4
            ),
        )
        return _take_gems_for_target(actor, legal, _shortfall(pstate, target), view["bank"])

    if mode == "points_rush":
        if buys:
            # Buy high-point cards or cheap stepping stones
            best_buy = max(
                buys,
                key=lambda a: (
                    engine.data.cards[a["card_id"]]["points"] * 3.0
                    + (0.8 if a["source"] == "reserved" else 0.0)
                    - sum(_shortfall(pstate, a["card_id"]).values()) * 0.2
                ),
            )
            c = engine.data.cards[best_buy["card_id"]]
            if c["points"] >= 1 or engine_size < 5:
                return best_buy

        # Target best points-per-deficit card (Tier 2/3 priority)
        scored_targets = sorted(
            visible_cards,
            key=lambda c: (
                engine.data.cards[c]["points"] / (1.0 + _net_deficit(pstate, c))
                + (0.3 if any(e["card_id"] == c for e in pstate["reserved"]) else 0.0)
            ),
            reverse=True,
        )
        target = scored_targets[0]
        # Reserve high-value card if close and gold is available
        if (
            reserves_market
            and view["bank"]["gold"] > 0
            and sum(pstate["tokens"].values()) <= 9
            and engine.data.cards[target]["points"] >= 3
            and 1 <= _net_deficit(pstate, target) <= 4
        ):
            match = next((a for a in reserves_market if a["card_id"] == target), None)
            if match is not None:
                return match
        return _take_gems_for_target(actor, legal, _shortfall(pstate, target), view["bank"])

    if mode == "noble_focus":
        if buys:
            return max(
                buys,
                key=lambda a: (
                    nweights[engine.data.cards[a["card_id"]]["bonus"]] * 4.0
                    + engine.data.cards[a["card_id"]]["points"] * 2.0
                    - sum(engine.data.cards[a["card_id"]]["cost"].values()) * 0.2
                ),
            )
        target = min(
            visible_cards,
            key=lambda c: (
                _net_deficit(pstate, c)
                - nweights[engine.data.cards[c]["bonus"]] * 2.5
                - engine.data.cards[c]["points"] * 0.5
            ),
        )
        return _take_gems_for_target(actor, legal, _shortfall(pstate, target), view["bank"])

    if mode == "reserve_control":
        if buys:
            return max(
                buys,
                key=lambda a: (
                    engine.data.cards[a["card_id"]]["points"] * 2.5
                    + (1.5 if a["source"] == "reserved" else 0.0)
                ),
            )
        # Aggressively reserve high-point cards (3-5 pts) when gold available
        if reserves_market and view["bank"]["gold"] > 0 and len(pstate["reserved"]) < 3 and sum(pstate["tokens"].values()) <= 9:
            high_val = [a for a in reserves_market if engine.data.cards[a["card_id"]]["points"] >= 2]
            if high_val:
                return max(
                    high_val,
                    key=lambda a: engine.data.cards[a["card_id"]]["points"] / (1.0 + _net_deficit(pstate, a["card_id"])),
                )
        target = min(visible_cards, key=lambda c: _net_deficit(pstate, c) - engine.data.cards[c]["points"] * 1.2)
        return _take_gems_for_target(actor, legal, _shortfall(pstate, target), view["bank"])

    return legal[0]


# ------------------------------------------------------------------
# Gymnasium Environment Wrapper for Splendor RL Policy Learning
# ------------------------------------------------------------------

MACRO_MODES = ["engine_build", "points_rush", "noble_focus", "reserve_control"]


class SplendorStrategyEnv(gym.Env):
    """Gymnasium Env where agent p1 selects a macro-strategy mode each turn against 3 opponents."""

    metadata = {"render_modes": []}

    def __init__(self, opponent_strategies: list[str]) -> None:
        super().__init__()
        self.opponent_strategies = opponent_strategies
        # State features: (my_pts_bucket: 0..3, opp_pts_bucket: 0..3, engine_bucket: 0..2, has_high_buy: 0..1)
        self.observation_space = spaces.MultiDiscrete([4, 4, 3, 2])
        self.action_space = spaces.Discrete(len(MACRO_MODES))
        self.state: dict[str, Any] = {}
        self._seed_counter = 1000

    def _obs(self) -> np.ndarray:
        p1 = self.state["players"]["p1"]
        my_pts = p1["points"]
        max_opp = max(p["points"] for pid, p in self.state["players"].items() if pid != "p1")
        eng = sum(p1["bonuses"].values())
        buys = [a for a in engine.get_legal_actions(self.state, "p1") if a["type"] == "BUY_CARD"]
        has_high_buy = 1 if any(engine.data.cards[a["card_id"]]["points"] >= 2 for a in buys) else 0

        my_b = 0 if my_pts < 4 else (1 if my_pts < 9 else (2 if my_pts < 13 else 3))
        opp_b = 0 if max_opp < 4 else (1 if max_opp < 9 else (2 if max_opp < 13 else 3))
        eng_b = 0 if eng < 4 else (1 if eng < 8 else 2)
        return np.array([my_b, opp_b, eng_b, has_high_buy], dtype=np.int64)

    def _advance_opponents(self) -> None:
        for _ in range(40):
            if engine.get_outcome(self.state) is not None:
                return
            actor = self.state["turn_order"][self.state["current_player_index"]]
            if actor == "p1" and self.state["phase"] == "MAIN_ACTION":
                return
            if actor == "p1":
                act = choose_splendor_action("points_rush", self.state, "p1")
            else:
                idx = self.state["turn_order"].index(actor) - 1
                act = choose_splendor_action(self.opponent_strategies[idx], self.state, actor)
            self.state = engine.apply_action(self.state, act).state

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        s = seed if seed is not None else self._seed_counter
        self._seed_counter += 1
        self.state = engine.setup({"players": ["p1", "p2", "p3", "p4"], "target_points": 15}, seed=s).state
        self._advance_opponents()
        return self._obs(), {}

    def step(self, action: int):
        mode = MACRO_MODES[int(action)]
        prev_pts = self.state["players"]["p1"]["points"]

        act = choose_splendor_action(mode, self.state, "p1")
        self.state = engine.apply_action(self.state, act).state

        # Finish any immediate DISCARD / CHOOSE_NOBLE for p1
        while engine.get_outcome(self.state) is None:
            actor = self.state["turn_order"][self.state["current_player_index"]]
            if actor != "p1":
                break
            sub = choose_splendor_action(mode, self.state, "p1")
            self.state = engine.apply_action(self.state, sub).state

        self._advance_opponents()

        outcome = engine.get_outcome(self.state)
        terminated = outcome is not None
        truncated = self.state["turn_number"] > 220

        reward = (self.state["players"]["p1"]["points"] - prev_pts) * 0.05
        if terminated:
            if "p1" in outcome["winners"]:
                reward += 1.0 / len(outcome["winners"])
            else:
                reward -= 1.0

        return self._obs(), float(reward), terminated, truncated, {"outcome": outcome}


def run_splendor_study() -> dict[str, Any]:
    # 1) 4-Player Benchmark: Consistent vs Situational (200 games with rotated seat order)
    lineup = ["engine_build", "points_rush", "noble_focus", "situational"]
    wins = defaultdict(float)
    avg_turns = []
    avg_cards = defaultdict(list)
    avg_nobles = defaultdict(list)

    n_games = 200
    for g in range(n_games):
        rot = lineup[g % 4 :] + lineup[: g % 4]
        pids = ["p1", "p2", "p3", "p4"]
        strat_map = dict(zip(pids, rot))
        state = engine.setup({"players": pids, "target_points": 15}, seed=5000 + g).state
        for _ in range(400):
            if engine.get_outcome(state) is not None:
                break
            actor = state["turn_order"][state["current_player_index"]]
            act = choose_splendor_action(strat_map[actor], state, actor)
            state = engine.apply_action(state, act).state
        out = engine.get_outcome(state)
        assert out is not None
        avg_turns.append(state["turn_number"] / 4.0)
        for pid in pids:
            s = strat_map[pid]
            avg_cards[s].append(len(state["players"][pid]["purchased"]))
            avg_nobles[s].append(len(state["players"][pid]["nobles"]))
        for w in out["winners"]:
            wins[strat_map[w]] += 1.0 / len(out["winners"])

    # Also test reserve_control vs top 3
    lineup2 = ["reserve_control", "points_rush", "engine_build", "situational"]
    wins2 = defaultdict(float)
    for g in range(120):
        rot = lineup2[g % 4 :] + lineup2[: g % 4]
        pids = ["p1", "p2", "p3", "p4"]
        strat_map = dict(zip(pids, rot))
        state = engine.setup({"players": pids, "target_points": 15}, seed=7000 + g).state
        for _ in range(400):
            if engine.get_outcome(state) is not None:
                break
            actor = state["turn_order"][state["current_player_index"]]
            act = choose_splendor_action(strat_map[actor], state, actor)
            state = engine.apply_action(state, act).state
        out = engine.get_outcome(state)
        assert out is not None
        for w in out["winners"]:
            wins2[strat_map[w]] += 1.0 / len(out["winners"])

    # 2) Gymnasium Q-Learning training (400 episodes) + evaluation (120 episodes)
    env = SplendorStrategyEnv(opponent_strategies=["engine_build", "points_rush", "noble_focus"])
    Q = np.zeros((4, 4, 3, 2, len(MACRO_MODES)), dtype=np.float64)
    rng = np.random.default_rng(42)

    alpha = 0.15
    gamma = 0.95
    for ep in range(400):
        eps = max(0.08, 0.45 * (1.0 - ep / 400.0))
        obs, _ = env.reset(seed=9000 + ep)
        done = False
        while not done:
            key = tuple(obs)
            if rng.random() < eps:
                act = int(rng.integers(0, len(MACRO_MODES)))
            else:
                act = int(np.argmax(Q[key]))
            nxt, rew, term, trunc, _ = env.step(act)
            done = term or trunc
            target = rew if done else rew + gamma * float(np.max(Q[tuple(nxt)]))
            Q[key][act] += alpha * (target - Q[key][act])
            obs = nxt

    # Evaluate learned Gymnasium Q-policy vs greedy baseline
    q_wins = 0.0
    eval_n = 120
    for ep in range(eval_n):
        obs, _ = env.reset(seed=20000 + ep)
        done = False
        while not done:
            act = int(np.argmax(Q[tuple(obs)]))
            obs, _, term, trunc, info = env.step(act)
            done = term or trunc
        if info["outcome"] and "p1" in info["outcome"]["winners"]:
            q_wins += 1.0 / len(info["outcome"]["winners"])

    # Extract learned situational preferences by game phase (my_pts_bucket)
    phase_prefs = {}
    phase_names = ["early(0-3pts)", "mid(4-8pts)", "late(9-12pts)", "endgame(13+pts)"]
    for b, name in enumerate(phase_names):
        sub_q = Q[b].mean(axis=(0, 1, 2))
        best_idx = int(np.argmax(sub_q))
        phase_prefs[name] = {
            "best_mode": MACRO_MODES[best_idx],
            "q_values": {MACRO_MODES[i]: round(float(sub_q[i]), 3) for i in range(len(MACRO_MODES))},
        }

    return {
        "benchmark_1_win_rates_pct": {k: round(100.0 * wins[k] / n_games, 1) for k in lineup},
        "benchmark_1_avg_rounds": round(float(np.mean(avg_turns)), 1),
        "benchmark_1_avg_cards": {k: round(float(np.mean(avg_cards[k])), 1) for k in lineup},
        "benchmark_1_avg_nobles": {k: round(float(np.mean(avg_nobles[k])), 2) for k in lineup},
        "benchmark_2_with_reserve_win_rates_pct": {k: round(100.0 * wins2[k] / 120, 1) for k in lineup2},
        "gym_qlearning_win_rate_pct": round(100.0 * q_wins / eval_n, 1),
        "gym_qlearning_phase_policy": phase_prefs,
    }


if __name__ == "__main__":
    print(json.dumps(run_splendor_study(), indent=2, ensure_ascii=False))
