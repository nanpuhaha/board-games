# 01. Overview & Glossary — Clue (Classic + Question Mark Cards)

## 게임 목표
저택에서 발생한 살인 사건의 **범인(Suspect)**, **범행 도구(Weapon)**, **범행 장소(Room)** 3가지 비밀 카드를 다른 플레이어보다 먼저 정확히 맞혀 최종 추리(Accusation)에 성공하면 승리한다.

## 기본 사양
- **인원**: 3–6인
- **추리 카드(21장)**: 용의자 6장 + 도구 6장 + 장소 9장 ([`data/cards.json`](../data/cards.json))
- **물음표(`?`) 보너스 카드(13장)**: `config.enable_bonus_cards = true`일 때 사용 ([`data/bonus-cards.json`](../data/bonus-cards.json))
- **보드**: 24×25 격자, 9개 방, 2쌍의 비밀 통로(`kitchen <-> study`, `conservatory <-> lounge`), 6개의 물음표(`?`) 복도 칸 ([`data/board.json`](../data/board.json))

## 핵심 용어 (Glossary)
- **사건 봉투 (Envelope)**: 게임 시작 시 용의자·도구·장소에서 1장씩 무작위로 뽑아 넣은 정답 3장 (`hidden`).
- **추리 (Suggestion)**: 방 안에서 `현재 방 + 임의의 용의자 + 임의의 도구`를 선언하고, 시계 방향 순서로 다른 플레이어가 반박 카드를 제시하도록 요청하는 행동.
- **반박 (Disprove)**: 추리된 3장 중 1장 이상을 보유한 첫 번째 시계 방향 플레이어가 그중 1장을 질문자에게만 비공개로 보여주는 행동.
- **최종 추리 (Accusation)**: 정답 3장을 공식 선언하는 행동. 맞히면 즉시 승리, 틀리면 탈락(단, 이후 반박 의무는 유지).
- **물음표 보너스 카드 (Question Mark / Bonus Card)**: 복도의 `?` 칸에 도착했을 때 덱 맨 위에서 1장을 뽑아 즉시 처리하고 덱 맨 아래로 되돌리는 특수 이벤트 카드.
- **소환 플래그 (`pulled_into_room`)**: 다른 플레이어의 추리에 의해 자신의 캐릭터가 특정 방으로 강제 이동되었을 때 설정되는 플래그. 다음 자기 턴에 주사위를 굴리지 않고도 그 방에서 바로 추리할 수 있다.
