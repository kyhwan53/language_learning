# Daily Language Queue

매일 아침 **영어 리스닝(비즈니스/환경공학 R&D 중심) + 일본어 입문 + 외신 읽기**를 메일로 보내고,
같은 에피소드를 모은 **개인 팟캐스트 피드**(`docs/feed.xml`)를 GitHub Pages로 게시하는 도구입니다.
외부 팟캐스트의 오디오는 재호스팅하지 않고 원본 URL만 가리킵니다. 외부 유료 API는 쓰지 않습니다(추가 비용 0원).

## 목표
- 영어: OPIc AL, 비즈니스(환경공학 R&D 회의/발표/협상) 영어. 우선순위는 **리스닝**(출퇴근용). 스피킹은 후순위.
- 일본어: 입문 → 여행 회화 수준. 하루 20~30분.

## 구조
| 파일 | 역할 |
|---|---|
| `config.toml` | **사용자가 고치는 유일한 설정**: 팟캐스트 소스, 외신 기사 소스, 요일별 편성, 수신/게시 주소 |
| `sources.py` | config.toml 로드/검증 |
| `build_daily.py` | 오늘의 큐 선정 → `docs/feed.xml` 생성 → 메일 HTML 생성/발송 |
| `manage.py` | 소스 추가/삭제/점검 CLI |
| `docs/feed.xml` | GitHub Pages로 게시되는 개인 피드 (안드로이드 AntennaPod 등에서 구독) |
| `state.json` | 이미 쓴 에피소드/기사 기록 (git 제외, 로컬 전용) |
| `out/email.html` | 마지막으로 만든 메일 미리보기 (git 제외) |

피드 주소: `https://kyhwan53.github.io/language_learning/feed.xml`

## 새 컴퓨터에서 이식하기
1. **Python 3.11+ 설치** (표준 라이브러리만 사용, `pip install` 불필요). Windows는 python.org 설치본 권장.
   Microsoft Store 별칭(`WindowsApps\python.exe`)은 동작하지 않을 수 있으니 실제 경로로 실행하세요.
2. **Git 설치** 후 클론:
   ```
   git clone https://github.com/kyhwan53/language_learning.git
   cd language_learning
   ```
   첫 `git push` 때 브라우저 로그인 창이 뜹니다 (GitHub `kyhwan53` 계정).
3. **Gmail 앱 비밀번호를 환경변수로 설정** (파일에 저장 금지, 공개 저장소임):
   ```
   [Environment]::SetEnvironmentVariable("GMAIL_USER","<본인 Gmail 주소>","User")
   [Environment]::SetEnvironmentVariable("GMAIL_APP_PASSWORD","<16자리 앱 비밀번호>","User")
   ```
   앱 비밀번호는 Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호에서 발급. 새 터미널을 열어야 반영됩니다.
4. **동작 확인**:
   ```
   python manage.py check          # 모든 피드가 살아 있는지
   python build_daily.py           # 메일 미리보기만 생성 (발송 안 함) → out/email.html
   python build_daily.py --send    # 실제 발송
   ```
5. **(선택) 진행 상태 이어받기**: `state.json`은 git에 올라가지 않습니다. 이전 컴퓨터의 `state.json`을 복사해 오면
   일본어 진도(1화부터 순서대로)와 중복 방지 기록이 이어집니다. 없으면 처음부터 시작합니다.
6. **매일 자동 실행은 GitHub Actions가 합니다** (`.github/workflows/daily.yml`, 매일 06:00 KST = 21:00 UTC, PC 불필요).
   저장소 Settings → Secrets and variables → Actions에 `GMAIL_USER`, `GMAIL_APP_PASSWORD`를 등록해야 동작합니다.
   수동 실행: 저장소 Actions 탭 → Daily language plan → Run workflow.
   실행 결과(`docs/feed.xml`, `state.json`)는 봇이 저장소에 commit합니다.

> **로컬에서 `--send`로 직접 보내지 마세요.** Actions가 `state.json`을 저장소에서 관리하므로, 로컬에서 실행하면 상태가 어긋납니다.
> 로컬 테스트는 `python build_daily.py`(발송 없음)만 쓰고, 그 뒤 `git checkout state.json docs/feed.xml`로 되돌리거나 `git pull`로 최신 상태를 받으세요.

## 시장 지표 / 경제 일정 (`indicators.py`)
메일 하단에 미국채 2Y/10Y/30Y 금리와 10Y-2Y 스프레드(US Treasury 공식 CSV), USD/KRW·JPY·EUR(Frankfurter/ECB),
앞으로 3일간 주요 통화(USD/EUR/GBP/JPY/CNY)의 고영향 경제지표 일정(Forex Factory 주간 JSON, KST 환산)을 넣습니다.
모든 블록은 실패해도 메일이 나가도록 개별 처리됩니다. 경제 일정 서버는 요청 제한(429)이 엄격해서
마지막 성공 결과를 `state.json`의 `calendar_cache`에 보관하고 실패 시 그것을 씁니다.

## 소스 바꾸기
`config.toml`을 직접 편집하거나 CLI를 씁니다.
```
python manage.py list
python manage.py check
python manage.py preview <RSS주소>
python manage.py add <key> "<이름>" <RSS주소> --mode newest   # newest | oldest(순서대로)
python manage.py remove <key>
python manage.py schedule mon biz,aee,jp
```
외신 기사(`[[article]]`)는 **짝수 개**로 유지하세요 (경제 → 국제정세 짝으로 하루 2건씩 회전).
잘못된 설정은 저장 전에 검증되어 오류로 알려주고, `manage.py`는 실패 시 파일을 원복합니다.

## 현재 소스
- 영어: BBC Learning English For Work, BBC 6 Minute English, NPR Short Wave, TED Talks Daily, All Ears English, NPR Life Kit
- 일본어: Nihongo con Teppei (1화부터 순서대로)
- 외신: BBC/NPR/Guardian의 Business·Economy와 World

## 로드맵 / 남은 일
- [ ] 매일 오전 자동 실행 (작업 스케줄러) — 코드 다듬은 뒤 진행하기로 함
- [ ] AntennaPod(안드로이드)에서 피드 구독
- [ ] 환경공학 R&D 회의/발표/협상 보충 에피소드 (주 1회 Claude로 대본 생성 → edge-tts → mp3 → 피드). Claude API는 쓰지 않고 구독 한도 내에서 수동 생성
- [ ] 일본어 여행 회화 단계별 레슨 (히라가나 → 카타카나 → 여행 상황)
- [ ] 기사에서 업무 영어 표현 추출 칸
- [ ] (후순위) 스피킹 연습/OPIc 모의

## 결정 사항 (바꾸지 않기로 한 것)
- Claude API 같은 유료 호출 금지: 구독료 이상의 지출 없음.
- 메일에는 mp3 링크를 넣지 않음. 개인 피드는 팟캐스트 앱 자동 다운로드용으로 원본 오디오 URL을 유지.
- 듣기는 안드로이드 **AntennaPod**에서 개인 피드를 구독해서 함 (Add podcast by RSS address → 위 피드 주소, 자동 다운로드/큐 추가 켜기).
  YouTube Music에는 개인 피드를 등록할 수 없고(소유권 인증 필요, 타사 콘텐츠), 에피소드를 YouTube 영상에 매칭하는 방식은
  정확도가 낮아 제거함. 메일에는 공식 페이지/대본 링크만 둠.
- 수신 메일 주소는 공개 저장소라 config에 적지 않음 (`recipient`가 비어 있으면 `GMAIL_USER`로 발송).
- Slow English 팟캐스트는 보류(동명 프로그램이 여럿이라 선택 필요).
- 외신 기사는 제목/요약/링크만 사용하고 전문은 복사하지 않음.
