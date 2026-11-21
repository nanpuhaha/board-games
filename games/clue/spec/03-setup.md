# 03. Setup Rules

`setup(config, seed)`는 아래 절차를 결정론적 순서로 수행한다.

## 입력 `config`
```json
{
  "players": [
    { "id": "p1", "suspect": "scarlett" },
    { "id": "p2", "suspect": "mustard" },
    { "id": "p3", "suspect": "white" }
  ],
  "enable_bonus_cards": true,
  "accusation_requires_room": false
}
```

## 검증 조건
- `players` 길이는 `3 <= len <= 6`이어야 한다. (위반 시 `INVALID_PLAYER_COUNT`)
- 모든 `id`와 `suspect`는 고유하고, `suspect`는 `data/cards.json`에 존재해야 한다. (위반 시 `INVALID_CONFIG`)

## 결정론적 세팅 절차 (RNG 호출 순서 고정)
`rng = Random(seed)`를 사용하여 아래 순서대로 처리한다.

1. **턴 순서 정렬**: 클래식 규칙에 따라 `scarlett -> mustard -> white -> green -> peacock -> plum` 순(`turn_order` 오름차순)으로 `turn_order`를 결정한다.
2. **말 초기 배치**: 6명의 모든 용의자 말(미참여 용의자 포함)을 `data/board.json`의 `start_positions` 복도 좌표에 배치한다.
3. **도구 초기 배치**: 9개 방 목록을 셔플(`rng.shuffle`)한 뒤, 6개 도구를 순서대로 서로 다른 방에 1개씩 배치한다.
4. **사건 봉투 생성**:
   - 용의자 6장, 도구 6장, 장소 9장을 각각 셔플한 뒤 각 첫 번째 카드를 `envelope`에 넣는다.
5. **카드 분배**:
   - 남은 18장을 합쳐 1회 셔플한다.
   - `turn_order` 순서대로 라운드 로빈으로 1장씩 모두 분배한다. (인원에 따라 1장 차이 가능)
6. **보너스 덱 준비**:
   - `enable_bonus_cards == true`이면 `data/bonus-cards.json`의 13장 ID를 셔플하여 `bonus_deck`에 넣는다. (`false`이면 빈 리스트)
7. **초기 페이즈 설정**:
   - `turn_number = 1`, `current_player_index = 0`, `phase = "TURN_START"`.
8. **초기 이벤트 발행**:
   - `GAME_STARTED` (`public`)
   - 각 플레이어별 `CARDS_DEALT` (`private`, `recipients: [player_id]`)
