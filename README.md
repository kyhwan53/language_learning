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
6. **(선택) 매일 자동 실행**: 아직 설정 전입니다. 계획: 작업 스케줄러로 오전에
   `python build_daily.py --send` 실행 후 `docs/feed.xml`을 commit/push. PC가 켜져 있어야 동작합니다.

> 두 컴퓨터에서 동시에 돌리면 `docs/feed.xml`과 `state.json`이 어긋납니다. **자동 실행은 한 대에서만** 하세요.

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
- YouTube Music에 개인 피드를 등록할 수 없음(소유권 인증 필요, 타사 콘텐츠). 대신 메일에 YouTube Music 검색 링크 제공.
- 수신 메일 주소는 공개 저장소라 config에 적지 않음 (`recipient`가 비어 있으면 `GMAIL_USER`로 발송).
- Slow English 팟캐스트는 보류(동명 프로그램이 여럿이라 선택 필요).
- 외신 기사는 제목/요약/링크만 사용하고 전문은 복사하지 않음.
