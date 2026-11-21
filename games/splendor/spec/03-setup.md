# 03. Setup Rules

`setup(config, seed)`는 아래 절차를 결정론적 순서로 수행한다.

## 입력 `config`
```json
{
  "players": ["p1", "p2", "p3"],
  "target_points": 15
}
```

## 검증 조건
- `players` 길이는 `2 <= len <= 4` (`INVALID_PLAYER_COUNT`)
- 모든 플레이어 ID는 비어 있지 않고 고유해야 함 (`INVALID_CONFIG`)
- `target_points >= 1` (`INVALID_CONFIG`)

## 결정론적 세팅 절차 (`rng = Random(seed)`)
1. `data/setup-tables.json`에서 인원수에 맞는 `gem_tokens_each`, `gold_tokens`, `nobles_count`를 로드해 `bank` 초기화.
2. `data/cards.json`의 카드를 단계별(`"1"`, `"2"`, `"3"`)로 분리하고 각 덱을 `rng.shuffle`한 뒤, 각 단계 맨 위 4장을 뽑아 `market`에 배치.
3. `data/nobles.json`의 10명 귀족 ID를 `rng.shuffle`한 뒤 상위 `nobles_count`명을 `nobles`에 배치.
4. 모든 플레이어의 `tokens`(전부 0), `bonuses`(전부 0), `purchased=[]`, `reserved=[]`, `nobles=[]`, `points=0` 초기화.
5. `turn_number = 1`, `current_player_index = 0`, `phase = "MAIN_ACTION"`, `final_round = False`.
6. 초기 이벤트 발행: `GAME_STARTED` (`public`), `TURN_STARTED` (`public`).
