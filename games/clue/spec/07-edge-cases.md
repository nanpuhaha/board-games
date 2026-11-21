# 07. Edge Cases & Ambiguity Resolution

에이전트가 구현 시 혼동하기 쉬운 엣지 케이스를 명시적으로 규정한다.

1. **탈락한 플레이어의 반박 의무**:
   - 최종 추리에 실패해 `eliminated == True`가 된 플레이어는 더 이상 자기 차례를 진행하지 못하지만, 손패는 공개하지 않으며 다른 플레이어의 추리에 대한 **반박(`DISPROVE`) 순서에는 계속 참여**한다.
   - 또한 보너스 카드(`peek_opponent_card`, `peek_left_card`, `force_public_reveal`)의 대상이 될 수도 있다.
2. **추리에 의한 소환과 다음 턴 행동**:
   - 플레이어 B의 말이 플레이어 A의 추리로 인해 방 R로 끌려오면 `players[B].pulled_into_room = True`가 된다.
   - B는 자신의 다음 `TURN_START`에서 주사위를 굴리지 않고 `STAY_FOR_SUGGESTION`을 선택해 R에서 바로 추리할 수 있다.
   - 만약 B가 `ROLL_DICE`나 `USE_SECRET_PASSAGE`를 선택하면 `pulled_into_room`은 `False`로 초기화된다.
3. **물음표(`?`) 보너스 카드 연쇄 방지**:
   - `bonus_move`(+6) 카드로 부여된 `BONUS_MOVE` 페이즈에서 또 다른 `?` 칸에 멈추더라도 **추가 보너스 카드를 뽑지 않는다** (무한 루프 방지).
   - 보너스 카드 사용 후에는 즉시 `bonus_deck` 맨 아래로 되돌아가므로 덱이 고갈되지 않는다.
4. **보너스 카드 `extra_turn`과 오답 최종 추리**:
   - `extra_turn_pending == True`인 상태에서 같은 턴에 잘못된 `MAKE_ACCUSATION`으로 탈락하면 추가 턴은 즉시 취소된다.
5. **문(Doorway) 차단과 방 진입**:
   - 복도 칸과 마찬가지로 출입구(doorway) 복도 칸에 다른 말이 서 있으면 그 칸을 통과하거나 멈출 수 없다.
   - 방에 진입할 때는 남은 이동력이 정확히 0이 아니어도 진입 가능하며, 진입 즉시 남은 이동력은 0이 된다.
6. **자기 자신을 추리(Suggestion)에 지목**:
   - 허용된다. 이 경우 이미 현재 방에 있으므로 `pulled_into_room`은 설정하지 않는다.
7. **이동 가능한 칸이 0개인 경우 (완전 포위)**:
   - `MOVE` 또는 `BONUS_MOVE` 페이즈에서 인접 칸/출입구가 모두 다른 말로 막혀 합법적인 이동 목적지가 하나도 없을 경우, 데드락 방지를 위해 `END_TURN`을 허용한다.
