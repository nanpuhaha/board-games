# 06. Scoring & End Conditions

클루는 점수제가 아닌 **단일 승자 또는 전원 탈락(무승부/미해결)** 구조이다.

## 종료 조건
1. **정답 최종 추리 (`CORRECT_ACCUSATION`)**:
   - 플레이어가 선언한 `(suspect, weapon, room)`이 `envelope`와 3장 모두 일치하면 해당 플레이어가 즉시 승리한다.
2. **전원 탈락 (`ALL_ELIMINATED`)**:
   - 마지막 생존 플레이어까지 오답 최종 추리로 탈락하면 승자 없이(`winner: null`) 사건 미해결로 종료된다.
   - *(참고: 클래식 룰에서 1명만 남았을 때는 자동 승리가 아니라, 마지막 생존자가 여전히 정답을 맞혀야 승리한다.)*

## `Outcome` 객체 스키마
```json
{
  "winner": "p1",
  "reason": "CORRECT_ACCUSATION",
  "envelope": {
    "suspect": "scarlett",
    "weapon": "candlestick",
    "room": "kitchen"
  }
}
```
- 진행 중일 때 `get_outcome(state)`는 `null`(`None`)을 반환한다.
- 게임 종료 시(`phase == "GAME_OVER"`) `envelope`는 모든 플레이어에게 공개된다.
