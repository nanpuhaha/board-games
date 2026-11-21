# 06. Scoring & End Conditions

## 점수 계산
- **개발 카드**: 구매한 카드의 `points` 합 (`0~5`점)
- **귀족 타일**: 영입한 귀족 1명당 `3`점
- `player.points = sum(card.points for card in purchased) + 3 * len(nobles)`

## 종료 조건 (동등한 턴 수 보장)
1. 어느 플레이어든 턴 종료 시점에 `points >= config.target_points` (기본 15점)에 도달하면 `final_round = True`가 된다.
2. 현재 라운드의 마지막 플레이어(`current_player_index == len(turn_order) - 1`)가 턴을 마칠 때까지 게임을 계속한다.
3. 라운드가 끝나면 게임이 종료되고(`phase = "GAME_OVER"`), 아래 우선순위로 승자를 결정한다.

## 타이브레이커 우선순위
1. **최고 명성 점수** (`points` 내림차순)
2. **구매한 개발 카드 수가 가장 적은 플레이어** (`len(purchased)` 오름차순)
3. 위 두 기준까지 모두 동일하면 **공동 승리** (`winners`에 동점자 전원 포함, `winner: null`).

## `Outcome` 스키마
```json
{
  "winner": "p1",
  "winners": ["p1"],
  "reason": "FINAL_ROUND_COMPLETED",
  "standings": [
    { "player": "p1", "points": 16, "purchased_count": 9, "nobles_count": 1 },
    { "player": "p2", "points": 15, "purchased_count": 10, "nobles_count": 1 }
  ]
}
```
