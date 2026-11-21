# board-games

AI 에이전트가 읽고 즉시 구현·검증할 수 있는 **언어 중립적 보드게임 규칙 스펙 + Python 레퍼런스 엔진** 레포지토리입니다.

## 핵심 특징

- **Agent-First Spec**: 상태 모델(가시성 구분), 턴 상태 머신, 액션별 Precondition/Effect/Error, 엣지 케이스, 도메인 이벤트 로그를 표준 형식으로 기술
- **Data / Logic 분리**: 카드, 보드 토폴로지, 보너스 카드 덱을 `data/*.json`으로 분리
- **언어 중립적 Conformance Tests**: `Given(state) + When(action) -> Then(expected state / events / error)` JSON 테스트 벡터로 어떤 언어 구현체든 동일하게 검증 가능
- **Python 레퍼런스 엔진**: 스펙의 실행 가능한 오라클(Oracle)이자 테스트 벡터 검증기

## 디렉토리 구조

```text
board-games/
├── AGENTS.md           # AI 에이전트용 진입점 및 엔진 계약
├── schemas/            # manifest / conformance / domain-event JSON Schema
├── templates/          # 새 게임 추가용 표준 템플릿
├── engine/             # Python 레퍼런스 엔진 공통 인터페이스 & Conformance 러너
├── scripts/            # 스키마 및 데이터 참조 무결성 검증 CLI
└── games/
    └── clue/           # 파일럿 게임: Clue (Classic + 물음표 보너스 카드)
```

## 게임 카탈로그

| 게임 | 슬러그 | 인원 | 상태 | 비고 |
|---|---|---|---|---|
| **Clue (클루)** | [`clue`](games/clue/manifest.yaml) | 3–6인 | 구현·검증 완료 | 클래식 기준 + 물음표(`?`) 보너스 카드 포함 |
| **Splendor (스플렌더)** | [`splendor`](games/splendor/manifest.yaml) | 2–4인 | 구현·검증 완료 | 클래식 90장 카드·10명 귀족·비공개 예약 마스킹 포함 |

## 빠른 시작

```bash
# 스키마 및 참조 무결성 검증
.venv/bin/python scripts/validate.py

# 레퍼런스 엔진 및 Conformance 테스트 실행
.venv/bin/pytest -v
```