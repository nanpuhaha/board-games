# 08. Domain Events Specification

모든 이벤트는 [`schemas/domain-event.schema.json`](../../../schemas/domain-event.schema.json)을 준수한다.

| 이벤트 `type` | `visibility` | `recipients` | 주요 `payload` 필드 |
|---|---|---|---|
| `GAME_STARTED` | `public` | — | `turn_order`, `target_points`, `nobles` |
| `TURN_STARTED` | `public` | — | `player`, `turn_number`, `final_round` |
| `TOKENS_TAKEN` | `public` | — | `player`, `tokens` |
| `TOKENS_DISCARDED` | `public` | — | `player`, `tokens` |
| `CARD_RESERVED` | `public` | — | `player`, `source`, `tier`, `gold_gained`, `card_id` *(마켓 예약 시에만 포함)* |
| `BLIND_CARD_RESERVED` | `private` | `[player]` | `player`, `tier`, `card_id` |
| `CARD_REVEALED_TO_MARKET` | `public` | — | `tier`, `card_id` |
| `CARD_PURCHASED` | `public` | — | `player`, `source`, `card_id`, `paid`, `points_gained` |
| `NOBLE_VISITED` | `public` | — | `player`, `noble_id`, `points_gained` |
| `FINAL_ROUND_TRIGGERED` | `public` | — | `triggered_by`, `points` |
| `TURN_PASSED` | `public` | — | `player` |
| `TURN_ENDED` | `public` | — | `player` |
| `GAME_ENDED` | `public` | — | `winner`, `winners`, `reason`, `standings` |
