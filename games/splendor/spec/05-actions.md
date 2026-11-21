# 05. Actions (Preconditions, Effects, Errors)

모든 액션은 공통 필드 `type: str`, `player: str`을 가진다.

## 공통 검증
1. `state.phase == "GAME_OVER"` → `GAME_ALREADY_OVER`
2. `player`가 `state.players`에 없음 → `UNKNOWN_PLAYER`
3. `player != turn_order[current_player_index]` → `NOT_YOUR_TURN`
4. 현재 페이즈에서 허용되지 않는 액션 → `INVALID_PHASE`

---

## 1. 메인 액션 (`phase == "MAIN_ACTION"`)

### `TAKE_THREE_GEMS`
- **파라미터**: `gems: list[gem]`
- **사전 조건**:
  - `gems`는 모두 서로 다른 일반 보석(`gold` 불가)이며 중복 없음 (`INVALID_GEM_SELECTION`)
  - 은행에 `>= 1`개인 보석 색 수 `avail = count(g for g in GEMS if bank[g] >= 1)`.
    - `avail >= 3`이면 `len(gems) == 3`이어야 함
    - `1 <= avail < 3`이면 `len(gems) == avail`이어야 함 (가져갈 수 있는 색을 모두 1개씩 획득)
    - `avail == 0`이면 불가 (`INSUFFICIENT_BANK_TOKENS`)
  - 선택한 모든 보석이 `bank[g] >= 1` (`INSUFFICIENT_BANK_TOKENS`)
- **효과**: 선택한 각 보석 `bank[g] -= 1`, `player.tokens[g] += 1`. 이벤트 `TOKENS_TAKEN`. 이후 턴 종료 파이프라인 실행.

### `TAKE_TWO_SAME_GEM`
- **파라미터**: `gem: gem` (`gold` 불가, `INVALID_GEM_SELECTION`)
- **사전 조건**: `bank[gem] >= 4` (`INSUFFICIENT_BANK_TOKENS`)
- **효과**: `bank[gem] -= 2`, `player.tokens[gem] += 2`. 이벤트 `TOKENS_TAKEN`. 이후 턴 종료 파이프라인 실행.

### `RESERVE_CARD`
- **파라미터**:
  - 마켓 예약: `source: "market"`, `card_id: str`
  - 덱 비공개 예약: `source: "deck"`, `tier: 1 | 2 | 3`
- **사전 조건**:
  - `len(player.reserved) < 3` (`RESERVE_LIMIT_REACHED`)
  - `source == "market"`: `card_id`가 `market`에 존재 (`CARD_NOT_IN_MARKET`)
  - `source == "deck"`: `decks[str(tier)]`가 비어 있지 않음 (`EMPTY_DECK`)
- **효과**:
  - 마켓 예약: `market`에서 제거해 `player.reserved`에 `{"card_id", "tier", "face_down": false}` 추가, 해당 단계 덱에 카드가 있으면 1장 보충(`CARD_REVEALED_TO_MARKET`).
  - 덱 예약: `decks[str(tier)].pop(0)`를 `player.reserved`에 `{"card_id", "tier", "face_down": true}` 추가.
  - `bank["gold"] > 0`이면 `bank["gold"] -= 1`, `player.tokens["gold"] += 1`, `gold_gained = 1` (아니면 `0`).
  - 이벤트:
    - 마켓 예약: `CARD_RESERVED` (`public`, `card_id` 포함)
    - 덱 예약: `CARD_RESERVED` (`public`, `card_id` 미포함/`tier`만 공개) + `BLIND_CARD_RESERVED` (`private`, `recipients: [player]`, 실제 `card_id` 포함)
  - 이후 턴 종료 파이프라인 실행.

### `BUY_CARD`
- **파라미터**: `source: "market" | "reserved"`, `card_id: str`
- **사전 조건**:
  - `source == "market"`: `card_id`가 `market`에 존재 (`CARD_NOT_IN_MARKET`)
  - `source == "reserved"`: `card_id`가 `player.reserved`에 존재 (`CARD_NOT_RESERVED`)
  - **비용 지불 계산 (결정론적 공식)**:
    - 각 일반 보석 `g`에 대해 `net_cost[g] = max(0, card.cost[g] - player.bonuses[g])`
    - 각 일반 보석 지불량: `paid[g] = min(player.tokens[g], net_cost[g])`
    - 부족분 합: `gold_needed = sum(net_cost[g] - paid[g] for g in GEMS)`
    - `player.tokens["gold"] >= gold_needed`이어야 함 (`INSUFFICIENT_RESOURCES`)
- **효과**:
  - 각 `g`: `player.tokens[g] -= paid[g]`, `bank[g] += paid[g]`
  - `player.tokens["gold"] -= gold_needed`, `bank["gold"] += gold_needed`
  - 카드를 `market` 또는 `player.reserved`에서 제거하고 `player.purchased`에 추가
  - `player.bonuses[card.bonus] += 1`, `player.points += card.points`
  - `source == "market"`이고 해당 단계 덱에 카드가 있으면 1장 마켓 보충 (`CARD_REVEALED_TO_MARKET`)
  - 이벤트: `CARD_PURCHASED` (`public`, 지불 내역 포함)
  - 이후 턴 종료 파이프라인 실행.

---

## 2. 토큰 버리기 (`phase == "DISCARD_TOKENS"`)

### `DISCARD_TOKENS`
- **파라미터**: `tokens: dict[gem_or_gold, int]`
- **사전 조건**:
  - 모든 수량은 양의 정수이며 `player.tokens[k] >= tokens[k]` (`INVALID_DISCARD`)
  - 버린 뒤 남은 총 토큰 수가 정확히 `10`이어야 함 (`INVALID_DISCARD_COUNT`)
- **효과**: 지정한 토큰을 `player.tokens`에서 빼고 `bank`로 반환. 이벤트 `TOKENS_DISCARDED`. 이후 턴 종료 파이프라인(귀족 방문 검사부터) 계속 실행.

---

## 3. 귀족 선택 (`phase == "CHOOSE_NOBLE"`)

### `CLAIM_NOBLE`
- **파라미터**: `noble_id: str`
- **사전 조건**: `noble_id in state.pending_nobles` (`INVALID_NOBLE`)
- **효과**:
  - `nobles`에서 제거해 `player.nobles`에 추가, `player.points += 3`, `pending_nobles = []`
  - 이벤트 `NOBLE_VISITED` (`public`)
  - 이후 턴 종료 파이프라인(최종 라운드 검사 및 턴 전환) 계속 실행.
