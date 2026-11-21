# AGENTS.md — AI 에이전트 구현 가이드

이 레포지토리는 **AI 에이전트가 보드게임의 규칙을 읽고 어떤 언어로든 즉시 구현·검증할 수 있도록 설계된 스펙 저장소**입니다.

---

## 1. 레포지토리 탐색 순서 (Progressive Disclosure)

특정 게임 `games/<slug>/`를 구현할 때는 아래 순서로 읽으세요.

1. `games/<slug>/manifest.yaml` — 인원수, 변형 옵션, 데이터/테스트 파일 위치 확인
2. `games/<slug>/spec/01-overview.md` ~ `08-domain-events.md` — 상태, 세팅, 턴 흐름, 액션, 종료 조건, 엣지 케이스, 이벤트 규약
3. `games/<slug>/data/*.json` — 카드, 보드, 테이블 등 정적 데이터 (코드에 하드코딩하지 말고 그대로 로드/임포트)
4. `games/<slug>/tests/conformance/*.json` — 구현체가 반드시 통과해야 하는 언어 중립적 테스트 벡터
5. `games/<slug>/reference/engine.py` — (모호한 점이 있을 때만 참고) Python 레퍼런스 구현체

---

## 2. 표준 엔진 계약 (Engine Contract)

모든 게임 엔진은 순수 함수 기반 상태 머신으로 모델링됩니다.

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `setup` | `(config, seed) -> StepResult` | 시드 기반 결정론적 초기 상태 + 초기 도메인 이벤트 생성 |
| `get_legal_actions` | `(state, player_id) -> list[Action]` | 해당 플레이어가 현재 수행 가능한 합법적 액션 목록 |
| `apply_action` | `(state, action) -> StepResult` | 불변(Immutable) 상태 전이. 불법 액션 시 `RuleError(code, message)` 발생 |
| `get_player_view` | `(state, player_id) -> PlayerView` | 정보 비대칭을 반영해 `hidden` / 타인의 `private` 필드를 마스킹한 뷰 |
| `get_outcome` | `(state) -> Outcome \| None` | 게임 종료 시 승자·순위·종료 사유 반환, 진행 중이면 `None` |

### `StepResult` 구조
```json
{
  "state": { "...": "다음 GameState (원본 상태는 변경하지 않음)" },
  "events": [
    {
      "type": "EVENT_NAME",
      "visibility": "public | private | hidden",
      "recipients": ["p1"],
      "payload": { "...": "..." }
    }
  ]
}
```

---

## 3. 가시성(Visibility) 규약

모든 상태 필드와 도메인 이벤트는 아래 3가지 가시성 중 하나를 가집니다.

- **`public`**: 모든 플레이어와 관전자가 볼 수 있음
- **`private`**: `recipients`에 명시된 특정 플레이어(들)만 볼 수 있음 (예: 본인 손패, 1:1 카드 공개)
- **`hidden`**: 엔진 내부에서만 유지되며 어떤 플레이어 뷰에도 노출되지 않음 (예: 비밀 봉투, 비공개 덱 순서)

---

## 4. 결정론(Determinism) 규약

- 모든 난수(셔플, 주사위 등)는 상태에 저장되거나 명시적으로 주입되는 시드/RNG를 사용합니다.
- Conformance 테스트에서는 주사위 결과 등 외부 난수를 액션 파라미터(또는 상태의 `rng_override`)로 고정하여 100% 재현 가능하게 검증합니다.

---

## 5. 검증 명령어

```bash
# 1) 모든 게임의 manifest / data / conformance JSON 스키마 및 참조 무결성 검증
.venv/bin/python scripts/validate.py

# 2) Python 레퍼런스 엔진 + Conformance 테스트 전체 실행
.venv/bin/pytest -v
```
