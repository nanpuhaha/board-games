# 08. Domain Events Specification

엔진의 `setup()`과 `apply_action()`은 상태 전이와 함께 구조화된 도메인 이벤트(`DomainEvent`) 리스트를 반환한다. 모든 이벤트는 [`schemas/domain-event.schema.json`](../../../schemas/domain-event.schema.json)을 준수한다.

| 이벤트 `type` | `visibility` | `recipients` | 주요 `payload` 필드 |
|---|---|---|---|
| `GAME_STARTED` | `public` | — | `turn_order`, `enable_bonus_cards` |
| `CARDS_DEALT` | `private` | `[player_id]` | `player`, `cards` |
| `TURN_STARTED` | `public` | — | `player`, `turn_number` |
| `DICE_ROLLED` | `public` | — | `player`, `dice`, `total` |
| `TOKEN_MOVED` | `public` | — | `suspect`, `from`, `to`, `reason` (`move` / `secret_passage` / `suggestion_pull` / `bonus_teleport` / `bonus_swap`) |
| `SECRET_PASSAGE_USED` | `public` | — | `player`, `from_room`, `to_room` |
| `STAYED_IN_ROOM` | `public` | — | `player`, `room` |
| `BONUS_CARD_DRAWN` | `public` | — | `player`, `card_id`, `effect` |
| `BONUS_CARD_PEEKED` | `private` | `[drawer, target_player]` | `drawer`, `from_player`, `card` |
| `CARD_REVEALED_PUBLICLY` | `public` | — | `owner`, `card`, `triggered_by` |
| `POSITIONS_SWAPPED` | `public` | — | `player_a`, `player_b` |
| `BONUS_EFFECT_RESOLVED` | `public` | — | `player`, `card_id`, `effect` |
| `SUGGESTION_MADE` | `public` | — | `suggester`, `suspect`, `weapon`, `room`, `from_bonus_card` |
| `DISPROVE_PASSED` | `public` | — | `player` |
| `SUGGESTION_DISPROVED` | `public` | — | `suggester`, `disprover` *(카드 정보 비포함)* |
| `CARD_SHOWN_PRIVATELY` | `private` | `[suggester, disprover]` | `from_player`, `to_player`, `card` |
| `SUGGESTION_UNDISPROVED` | `public` | — | `suggester` |
| `ACCUSATION_MADE` | `public` | — | `player`, `suspect`, `weapon`, `room`, `correct` |
| `PLAYER_ELIMINATED` | `public` | — | `player` |
| `TURN_ENDED` | `public` | — | `player`, `extra_turn` |
| `GAME_ENDED` | `public` | — | `winner`, `reason`, `envelope` |

> [!IMPORTANT]
> 서버/네트워크 계층은 `visibility == "private"` 이벤트를 `recipients`에 포함된 클라이언트에게만 전송하고, 나머지 클라이언트에게는 전송하지 않아야 한다.
