# 02. State Model & Visibility

## 최상위 `GameState` 스키마

| 필드 | 타입 | 가시성 | 설명 |
|---|---|---|---|
| `config` | `object` | `public` | `target_points: int` (기본 15) |
| `turn_number` | `int` | `public` | 1부터 시작하는 턴 번호 |
| `turn_order` | `list[str]` | `public` | 시계 방향 플레이어 ID 목록 |
| `current_player_index` | `int` | `public` | 현재 턴 플레이어 인덱스 |
| `phase` | `Phase` | `public` | `MAIN_ACTION \| DISCARD_TOKENS \| CHOOSE_NOBLE \| GAME_OVER` |
| `bank` | `dict[gem_or_gold, int]` | `public` | 공용 은행의 각 보석 및 `gold` 토큰 수량 |
| `decks` | `dict["1"\|"2"\|"3", list[card_id]]` | `hidden` | 각 단계별 비공개 덱 (인덱스 0이 맨 위). 뷰에서는 `deck_counts`만 노출 |
| `market` | `dict["1"\|"2"\|"3", list[card_id]]` | `public` | 각 단계별 공개된 마켓 카드 목록 (최대 4장) |
| `nobles` | `list[noble_id]` | `public` | 아직 영입되지 않은 귀족 타일 목록 |
| `players` | `dict[player_id, PlayerState]` | 혼합 | 아래 `PlayerState` 참조 |
| `final_round` | `bool` | `public` | 누군가 `target_points` 이상 달성해 마지막 라운드 진행 중인지 여부 |
| `pending_nobles` | `list[noble_id]` | `public` | `CHOOSE_NOBLE` 페이즈에서 선택 가능한 귀족 ID 목록 |
| `outcome` | `Outcome \| null` | `public` | 게임 종료 시 결과 객체, 진행 중이면 `null` |

## `PlayerState`
| 필드 | 타입 | 가시성 | 설명 |
|---|---|---|---|
| `id` | `str` | `public` | 플레이어 ID |
| `tokens` | `dict[gem_or_gold, int]` | `public` | 보유 중인 보석·황금 토큰 수량 |
| `bonuses` | `dict[gem, int]` | `public` | 구매한 카드로부터 얻은 영구 보석 보너스 수량 |
| `purchased` | `list[card_id]` | `public` | 구매 완료한 개발 카드 ID 목록 |
| `reserved` | `list[ReservedEntry]` | 혼합 | 최대 3장. `face_down == false`는 `public`, `face_down == true`는 `private(self)` |
| `nobles` | `list[noble_id]` | `public` | 영입한 귀족 ID 목록 |
| `points` | `int` | `public` | 현재 총 명성 점수 (구매 카드 점수 합 + 귀족 수 × 3) |

### `ReservedEntry`
- 내부 상태: `{"card_id": "t2_05", "tier": 2, "face_down": true}`
- 타인 뷰(`get_player_view(state, other_id)`) 마스킹 결과:
  - `face_down == false`: `{"card_id": "t2_05", "tier": 2, "face_down": false}`
  - `face_down == true`: `{"hidden": true, "tier": 2, "face_down": true}`

## 불변식 (Invariants)
1. 모든 `bank` + `players[*].tokens`의 합은 각 보석별 초기 공급량(`4/5/7`) 및 `gold=5`와 항상 같다.
2. 모든 `decks` + `market` + `players[*].reserved` + `players[*].purchased`의 합집합은 90장 카드 전체와 중복 없이 일치한다.
3. `MAIN_ACTION` 시작 시 모든 플레이어의 보유 토큰 합은 항상 `<= 10`이다.
4. `get_player_view(state, player_id)`는 `decks`를 절대 노출하지 않고 `deck_counts`만 제공하며, 타인의 `face_down` 예약 카드 `card_id`를 마스킹한다.
