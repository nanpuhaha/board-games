# New Game Template

새 게임을 추가할 때 `templates/_game-template/`를 `games/<slug>/`로 복사한 뒤 아래 파일을 채우세요.

1. `manifest.yaml` — 게임 메타데이터 및 파일 목록
2. `spec/01-overview.md` ~ `08-domain-events.md` — 표준 8개 스펙 문서
3. `data/*.json` — 정적 데이터 (카드, 보드, 테이블 등)
4. `tests/conformance/*.json` — 언어 중립적 테스트 벡터
5. `reference/engine.py` & `reference/test_<slug>.py` — Python 레퍼런스 엔진 및 pytest 검증
