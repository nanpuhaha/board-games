"""Language-agnostic JSON conformance test runner for Python reference engines."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from engine.contracts import GameEngine, RuleError


def assert_subset(expected: Any, actual: Any, path: str = "$") -> None:
    """Recursively verify that `expected` is a subset of `actual`."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual).__name__} ({actual!r})"
        for key, exp_val in expected.items():
            assert key in actual, f"{path}: missing key {key!r} in {actual!r}"
            assert_subset(exp_val, actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list, got {type(actual).__name__} ({actual!r})"
        assert len(expected) == len(actual), (
            f"{path}: expected list of length {len(expected)}, got {len(actual)} ({actual!r})"
        )
        for idx, (exp_item, act_item) in enumerate(zip(expected, actual)):
            assert_subset(exp_item, act_item, f"{path}[{idx}]")
    else:
        assert expected == actual, f"{path}: expected {expected!r}, got {actual!r}"


def _event_matches(expected_event: dict[str, Any], actual_event: dict[str, Any]) -> bool:
    try:
        assert_subset(expected_event, actual_event)
        return True
    except AssertionError:
        return False


def load_conformance_cases(conformance_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    """Load all conformance test cases from JSON files in a directory."""
    cases: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(conformance_dir.glob("*.json")):
        suite = json.loads(path.read_text(encoding="utf-8"))
        suite_name = suite["suite"]
        for case in suite["cases"]:
            cases.append((f"{suite_name}::{case['id']}", case))
    return cases


def run_conformance_case(engine: GameEngine, case: dict[str, Any]) -> None:
    """Execute a single language-agnostic conformance test case against `engine`."""
    given_state = copy.deepcopy(case["given"])
    given_snapshot = copy.deepcopy(given_state)
    then = case["then"]

    if "when" in case:
        action = copy.deepcopy(case["when"])
        if "error" in then:
            try:
                engine.apply_action(given_state, action)
            except RuleError as exc:
                assert exc.code == then["error"], (
                    f"Case {case['id']}: expected RuleError({then['error']!r}), got RuleError({exc.code!r}: {exc.message})"
                )
            else:
                raise AssertionError(
                    f"Case {case['id']}: expected RuleError({then['error']!r}), but action succeeded"
                )
            assert given_state == given_snapshot, f"Case {case['id']}: engine mutated input state on error"
            return

        result = engine.apply_action(given_state, action)
        assert given_state == given_snapshot, f"Case {case['id']}: engine mutated input state"
        next_state = result.state
        events = result.events_as_dicts()

        if "state_subset" in then:
            assert_subset(then["state_subset"], next_state, "$.state")

        if "events_contain" in then:
            for exp_event in then["events_contain"]:
                matched = any(_event_matches(exp_event, act) for act in events)
                assert matched, (
                    f"Case {case['id']}: expected event matching {exp_event!r} not found in {events!r}"
                )
    else:
        next_state = given_state

    if "view_as" in case:
        view = engine.get_player_view(next_state, case["view_as"])
        if "view_subset" in then:
            assert_subset(then["view_subset"], view, f"$.view[{case['view_as']}]")
        for absent_key in then.get("view_absent_keys", []):
            assert absent_key not in view, (
                f"Case {case['id']}: forbidden key {absent_key!r} leaked into player view"
            )

    if "outcome" in then:
        actual_outcome = engine.get_outcome(next_state)
        if then["outcome"] is None:
            assert actual_outcome is None, f"Case {case['id']}: expected None outcome, got {actual_outcome!r}"
        else:
            assert_subset(then["outcome"], actual_outcome, "$.outcome")
