# 02. State Model & Visibility

모든 상태는 JSON 직렬화 가능한 순수 딕셔너리(불변 구조)로 표현된다.

## 최상위 `GameState` 스키마

| 필드 | 타입 | 가시성 | 설명 |
|---|---|---|---|
| `config` | `object` | `public` | `enable_bonus_cards: bool`, `accusation_requires_room: bool` |
| `rng_state` | `int` | `hidden` | 결정론적 시드/난수 진행 카운터 |
| `turn_number` | `int` | `public` | 1부터 시작하는 턴 번호 |
| `turn_order` | `list[str]` | `public` | 시계 방향 플레이어 ID 목록 |
| `current_player_index` | `int` | `public` | 현재 턴 플레이어의 `turn_order` 인덱스 |
| `phase` | `Phase` | `public` | 현재 상태 머신 페이즈 (`04-turn-flow.md` 참조) |
| `players` | `dict[player_id, PlayerState]` | 혼합 | 아래 `PlayerState` 참조 |
| `tokens` | `dict[suspect_id, Location]` | `public` | **모든 6명의 용의자** 말 위치 (미참여 용의자 포함) |
| `weapons` | `dict[weapon_id, room_id]` | `public` | 6개 도구의 현재 방 위치 |
| `envelope` | `Envelope` | `hidden` | `{suspect, weapon, room}` 정답 3장 |
| `bonus_deck` | `list[bonus_card_id]` | `hidden` | 물음표 보너스 카드 덱 (인덱스 0이 맨 위) |
| `dice` | `[int, int] \| null` | `public` | 이번 턴 주사위 결과 |
| `movement_remaining` | `int` | `public` | 현재 이동 페이즈에서 남은 최대 이동 칸 수 |
| `extra_turn_pending` | `bool` | `public` | 현재 턴 종료 후 같은 플레이어가 한 번 더 진행하는지 여부 |
| `pending_suggestion` | `SuggestionState \| null` | `public` | 진행 중인 추리 및 반박 대기 상태 |
| `pending_bonus` | `BonusResolution \| null` | `public` | 처리 중인 물음표 보너스 카드 상태 |
| `public_revealed_cards` | `list[{owner, card}]` | `public` | 보너스 카드(`force_public_reveal`) 등으로 모두에게 공개된 카드 기록 |
| `outcome` | `Outcome \| null` | `public` | 게임 종료 시 결과 객체, 진행 중이면 `null` |

## 하위 구조

### `Location`
- 복도: `{"kind": "hallway", "x": int, "y": int}`
- 방: `{"kind": "room", "room": room_id}`

### `PlayerState`
| 필드 | 타입 | 가시성 | 설명 |
|---|---|---|---|
| `id` | `str` | `public` | 플레이어 ID |
| `suspect` | `suspect_id` | `public` | 담당 용의자 |
| `hand` | `list[card_id]` | `private(self)` | 보유 추리 카드 목록 (타인 뷰에서는 `hand_count: int`로 대체) |
| `eliminated` | `bool` | `public` | 잘못된 최종 추리로 탈락했는지 여부 |
| `pulled_into_room` | `bool` | `public` | 이전 턴 사이 타인의 추리로 방에 소환되었는지 여부 |

### `SuggestionState`
```json
{
  "suggester": "p1",
  "suspect": "mustard",
  "weapon": "rope",
  "room": "kitchen",
  "responder_queue": ["p2", "p3"],
  "current_responder_index": 0,
  "from_bonus_card": false
}
```

### `BonusResolution`
```json
{
  "card_id": "bonus_peek_opponent_1",
  "effect": "peek_opponent_card",
  "drawer": "p1",
  "target_player": null,
  "step": "CHOOSE_TARGET | RESPOND_CARD | CHOOSE_ROOM | CHOOSE_SUGGESTION"
}
```

## 불변식 (Invariants)
1. `envelope`의 3장 + 모든 `players[*].hand`의 합집합은 항상 21장 추리 카드 전체와 정확히 일치하며 중복이 없다.
2. 복도(`kind == "hallway"`)의 같은 `(x, y)` 좌표에는 두 개 이상의 용의자 말이 동시에 존재할 수 없다.
3. 방(`kind == "room"`)에는 여러 용의자 말과 도구가 동시에 존재할 수 있다.
4. `get_player_view(state, player_id)`는 `envelope`, `bonus_deck`, `rng_state` 키를 절대 포함하지 않으며, 타인의 `hand`는 숨기고 `hand_count`만 노출한다.
