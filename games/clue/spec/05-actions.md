# 05. Actions (Preconditions, Effects, Errors)

모든 액션은 공통 필드 `type: str`, `player: str`을 가진다.

## 공통 검증 규칙
1. `state.phase == "GAME_OVER"` → `GAME_ALREADY_OVER`
2. `player`가 `state.players`에 없음 → `UNKNOWN_PLAYER`
3. 현재 페이즈에서 허용되지 않는 액션 → `INVALID_PHASE`
4. 행동 주체 불일치:
   - `DISPROVE` 페이즈에서는 `pending_suggestion.responder_queue[current_responder_index]`만 허용
   - `BONUS_RESOLVE`에서 `step == "RESPOND_CARD"`일 때는 `pending_bonus.target_player`만 허용
   - 그 외 모든 페이즈에서는 `turn_order[current_player_index]`만 허용
   - 위반 시 `NOT_YOUR_TURN`

---

## 1. 턴 시작 & 이동 액션

### `ROLL_DICE`
- **허용 페이즈**: `TURN_START`
- **파라미터**: `dice_override?: [int, int]` (테스트용 결정론적 주사위 주입; 1..6 정수 2개)
- **효과**:
  - 주사위 2개(`d1, d2`)를 굴려 `dice = [d1, d2]`, `movement_remaining = d1 + d2` 설정
  - 현재 플레이어의 `pulled_into_room = False`
  - `phase = "MOVE"`
  - 이벤트: `DICE_ROLLED`

### `USE_SECRET_PASSAGE`
- **허용 페이즈**: `TURN_START`
- **사전 조건**:
  - 현재 플레이어 말이 방(`kind == "room"`)에 있어야 함 (`NOT_IN_ROOM`)
  - 해당 방에 `secret_passage_to != null` (`NO_SECRET_PASSAGE`)
- **효과**:
  - 플레이어 말을 연결된 방으로 즉시 이동
  - `pulled_into_room = False`, `phase = "POST_MOVE"`
  - 이벤트: `SECRET_PASSAGE_USED`

### `STAY_FOR_SUGGESTION`
- **허용 페이즈**: `TURN_START`
- **사전 조건**:
  - `players[player].pulled_into_room == True`이고 현재 방에 있어야 함 (`CANNOT_STAY_WITHOUT_PULL`)
- **효과**:
  - 이동하지 않고 `pulled_into_room = False`, `phase = "POST_MOVE"`
  - 이벤트: `STAYED_IN_ROOM`

### `MOVE_TO_HALLWAY`
- **허용 페이즈**: `MOVE`, `BONUS_MOVE`
- **파라미터**: `x: int`, `y: int`
- **사전 조건**:
  - `(x, y)`가 보드 내 유효한 복도(`. ` 또는 `?`)이며 다른 말이 점유하지 않아야 함 (`TARGET_OCCUPIED` / `INVALID_DESTINATION`)
  - 현재 위치에서 다른 말에 막히지 않은 상하좌우 최단 경로 길이 `dist`가 `1 <= dist <= movement_remaining`이어야 함 (`UNREACHABLE_DESTINATION`)
    - 방에서 출발 시: 해당 방의 비어있는 출입구(doorway) 복도 칸으로 나오는 것이 1칸 이동
- **효과**:
  - 플레이어 말 위치를 `{"kind": "hallway", "x": x, "y": y}`로 이동, `movement_remaining = 0`
  - 이벤트: `TOKEN_MOVED`
  - **물음표(`?`) 칸 트리거**:
    - `phase == "MOVE"`이고 `config.enable_bonus_cards == True`이며 보드 `(x, y) == "?"`이고 `bonus_deck`이 비어있지 않으면:
      - `bonus_deck` 맨 위 카드를 뽑아 맨 아래로 이동(recycle)
      - 이벤트: `BONUS_CARD_DRAWN`
      - 카드 효과에 따라 즉시 처리(`extra_turn` → `POST_MOVE`, `bonus_move` → `BONUS_MOVE(movement_remaining=6)`, `peek_left_card` → `BONUS_RESOLVE(step="RESPOND_CARD")`) 또는 선택 대기(`BONUS_RESOLVE`)로 전이
    - 그 외(일반 복도 또는 `BONUS_MOVE` 중): `phase = "POST_MOVE"`

### `MOVE_TO_ROOM`
- **허용 페이즈**: `MOVE`, `BONUS_MOVE`
- **파라미터**: `room: room_id`
- **사전 조건**:
  - `room`이 유효한 방 ID (`INVALID_ROOM`)
  - 현재 이미 그 방 안에 있으면 불가 (`ALREADY_IN_ROOM`)
  - 해당 방의 출입구(doorway) 중 하나에 도달해 1칸 더 들어가기까지의 최단 경로 길이가 `<= movement_remaining`이어야 함 (정확한 숫자가 아니어도 진입 가능, 남은 칸은 소멸) (`UNREACHABLE_DESTINATION`)
- **효과**:
  - 플레이어 말 위치를 `{"kind": "room", "room": room}`으로 이동, `movement_remaining = 0`, `phase = "POST_MOVE"`
  - 이벤트: `TOKEN_MOVED`

---

## 2. 물음표 보너스 카드 해결 액션 (`BONUS_RESOLVE`)

### `BONUS_CHOOSE_ROOM` (`effect == "teleport_any_room"`)
- **파라미터**: `room: room_id`
- **효과**: 플레이어 말을 해당 방으로 즉시 이동, `pending_bonus = None`, `phase = "POST_MOVE"`, 이벤트 `BONUS_EFFECT_RESOLVED` + `TOKEN_MOVED`.

### `BONUS_CHOOSE_TARGET` (`effect in {"peek_opponent_card", "force_public_reveal", "swap_position"}`)
- **파라미터**: `target_player: player_id` (본인 불가, `INVALID_TARGET`)
- **효과**:
  - `swap_position`: 두 플레이어의 `tokens[suspect]` 위치를 즉시 맞교환, `pending_bonus = None`, `phase = "POST_MOVE"`, 이벤트 `POSITIONS_SWAPPED` + `BONUS_EFFECT_RESOLVED`.
  - `peek_opponent_card` / `force_public_reveal`: `pending_bonus.target_player = target_player`, `pending_bonus.step = "RESPOND_CARD"`. (만약 대상 손패가 0장이면 즉시 `POST_MOVE`로 종료)

### `BONUS_RESPOND_CARD` (`step == "RESPOND_CARD"`)
- **행동 주체**: `pending_bonus.target_player`
- **파라미터**: `card: card_id` (대상 손패에 있어야 함, `CARD_NOT_IN_HAND`)
- **효과**:
  - `peek_opponent_card` / `peek_left_card`: `BONUS_CARD_PEEKED` (`private`, `recipients: [drawer, target_player]`) 발행
  - `force_public_reveal`: `public_revealed_cards`에 `{owner: target_player, card}` 추가, `CARD_REVEALED_PUBLICLY` (`public`) 발행
  - `pending_bonus = None`, `phase = "POST_MOVE"`, 이벤트 `BONUS_EFFECT_RESOLVED`.

### `BONUS_MAKE_SUGGESTION` (`effect == "free_suggestion"`)
- **파라미터**: `suspect: suspect_id`, `weapon: weapon_id`, `room: room_id`
- **효과**: 현재 말 위치와 무관하게 지정한 `room`으로 추리 시작 (지목된 `suspect`와 `weapon`은 해당 `room`으로 소환되며, 만약 지목된 `suspect`가 다른 플레이어라면 `pulled_into_room = True`). `pending_bonus = None`, `phase = "DISPROVE"` (반박 큐가 비어 있으면 `POST_SUGGESTION`).

---

## 3. 추리 · 반박 · 최종 추리 · 턴 종료

### `MAKE_SUGGESTION`
- **허용 페이즈**: `POST_MOVE`
- **파라미터**: `suspect: suspect_id`, `weapon: weapon_id` (방은 자동으로 현재 플레이어가 위치한 방)
- **사전 조건**: 현재 플레이어가 방 안에 있어야 함 (`NOT_IN_ROOM`), 유효한 `suspect`/`weapon` (`INVALID_CARD`)
- **효과**:
  - `tokens[suspect] = {"kind": "room", "room": current_room}`
  - `weapons[weapon] = current_room`
  - 지목된 `suspect`를 조종하는 다른 플레이어가 존재하면 그 플레이어의 `pulled_into_room = True`
  - `responder_queue`: 현재 플레이어 다음부터 시계 방향의 모든 다른 플레이어 (**탈락한 플레이어도 포함!**)
  - `pending_suggestion` 설정, `phase = "DISPROVE"`
  - 이벤트: `SUGGESTION_MADE`

### `SHOW_DISPROVE_CARD`
- **허용 페이즈**: `DISPROVE`
- **파라미터**: `card: card_id`
- **사전 조건**: `card`가 추리 3장 중 하나이며 응답자 손패에 존재해야 함 (`INVALID_DISPROVE_CARD`)
- **효과**:
  - `pending_suggestion = None`, `phase = "POST_SUGGESTION"`
  - 이벤트:
    - `SUGGESTION_DISPROVED` (`public`, 카드 이름 미포함 — 누구가 반박했는지만 공개)
    - `CARD_SHOWN_PRIVATELY` (`private`, `recipients: [suggester, responder]`, 실제 `card` 포함)

### `PASS_DISPROVE`
- **허용 페이즈**: `DISPROVE`
- **사전 조건**: 응답자 손패에 추리 3장과 일치하는 카드가 **0장**이어야 함 (일치 카드가 있는데 패스하면 `MUST_DISPROVE`)
- **효과**:
  - 이벤트: `DISPROVE_PASSED` (`public`)
  - 다음 응답자가 있으면 `current_responder_index += 1`
  - 모든 응답자가 패스했으면 `pending_suggestion = None`, `phase = "POST_SUGGESTION"`, 이벤트 `SUGGESTION_UNDISPROVED` (`public`)

### `MAKE_ACCUSATION`
- **허용 페이즈**: `TURN_START`, `POST_MOVE`, `POST_SUGGESTION`
- **파라미터**: `suspect: suspect_id`, `weapon: weapon_id`, `room: room_id`
- **사전 조건**:
  - 유효한 용의자/도구/장소 ID (`INVALID_CARD`)
  - `config.accusation_requires_room == True`인 경우 현재 방 안에 있어야 함 (`NOT_IN_ROOM`)
- **효과**:
  - 이벤트: `ACCUSATION_MADE` (`public`)
  - **정답 일치**:
    - `phase = "GAME_OVER"`, `outcome = {"winner": player, "reason": "CORRECT_ACCUSATION", "envelope": envelope}`
    - 이벤트: `GAME_ENDED` (`public`)
  - **오답**:
    - `players[player].eliminated = True`, `extra_turn_pending = False`
    - 이벤트: `PLAYER_ELIMINATED` (`public`)
    - 모든 플레이어가 탈락했으면 `phase = "GAME_OVER"`, `outcome = {"winner": null, "reason": "ALL_ELIMINATED", "envelope": envelope}`, 이벤트 `GAME_ENDED`
    - 생존자가 남아 있으면 즉시 다음 생존 플레이어의 `TURN_START`로 턴 전환 (`TURN_ENDED` + `TURN_STARTED`)

### `END_TURN`
- **허용 페이즈**: `POST_MOVE`, `POST_SUGGESTION`
- **효과**:
  - 이벤트: `TURN_ENDED` (`public`)
  - `extra_turn_pending == True`이고 현재 플레이어가 탈락하지 않았으면:
    - `extra_turn_pending = False`, 같은 플레이어로 `turn_number += 1`, `phase = "TURN_START"`
  - 그렇지 않으면 시계 방향 다음 미탈락 플레이어로 이동, `turn_number += 1`, `phase = "TURN_START"`
  - `dice = None`, `movement_remaining = 0`
  - 이벤트: `TURN_STARTED` (`public`)
