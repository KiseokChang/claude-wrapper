# Claude CLI Wrapper 가이드

> 헤드리스 엔진(`claude -p`) 위에 메신저 연동 · 세션 관리 · 안전장치 · 멀티 에이전트 계층을 쌓기 위한 종합 정리
>
> - 원출처: 2026-09-06 Gemini 대화 내용을 "Claude CLI Wrapper" 주제 중심으로 재편집
> - 편집 방침: 본문은 래퍼(Wrapper) 구축의 핵심 흐름, 주변 주제는 부록으로 분리. 원문 내용은 최대한 보존

---

## 목차

**Part 1 — 기초**
- 1. `claude -p` 헤드리스 모드 기초
- 2. 실행 엔진 환경: DIRECT vs OLLAMA

**Part 2 — 최소 구현: 메신저 브릿지**
- 3. 텔레그램 브릿지 최소 구현
- 4. 통합 브릿지 `agent_bridge.py` (이중 모드)
- 5. 상호작용 유형 파싱과 UI 매핑
- 6. JSON 출력으로 커스텀 앱/UI 만들기

**Part 3 — 견고한 설계**
- 7. 어댑터 패턴으로 엔진 추상화
- 8. 안전 가드레일: 명령어 가로채기
- 9. 엔진 위에 얹을 수 있는 확장 레이어 5가지
- 10. 멀티 에이전트 오케스트레이션
- 11. 커스텀 TUI 만들기

**부록**
- A. MS Teams API 개요 · 응용 사례 · 사내 메신저(m-chat) 연동 확인 포인트
- B. GPU 서버(GX10) 특화 자동화 시나리오
- C. "채팅창에서 코드 실행"의 한계 분석과 대안
- D. 바이브 코딩 메신저 연동: 기존 사례와 사내 적용 전략
- E. Cline 계열 세션 저장 구조와 사내 포크(cline-sr) CLI 점검
- F. 에이전트 CLI 비교 (Claude Code / OpenClaw / Hermes / Cline / Aider)
- G. 텔레그램 멀티 에이전트 방 아키텍처
- H. 무인 운영 인프라: WOL · 자동 로그인 · 작업 스케줄러 · 전력 제어
- I. 서브 에이전트 자율 분동과 CLAUDE.md 설정 예시

---

# Part 1 — 기초

## 1. `claude -p` 헤드리스 모드 기초

### 1.1 개념

Claude Code CLI는 터미널 TUI뿐만 아니라 **비대화형(Headless/Print) 모드**를 1급 시민(First-class citizen)으로 제공한다. TUI 창을 띄우지 않고 명령 한 줄을 주입하고 최종 결과만 출력한다.

```bash
# 터미널 TUI 없이 한 줄 명령으로 실행하고 최종 결과만 출력
claude -p "현재 GPU VRAM 상태 확인하고 빈 디바이스에 bge-m3 테스트 스크립트 작성해서 실행해줘"
```

이 모드가 중요한 이유: **공식 채널(Telegram/Slack) 외의 사내 폐쇄망 메신저나 커스텀 웹챗(m-chat 등)에 Claude Code를 연결할 때의 표준 방식**이 되기 때문이다. 연동 구조는 다음과 같다.

```
[사내 메신저(m-chat 등)] 에서 사용자가 @bot으로 자연어 요청 전송
        │
        ▼ (Webhook / 소켓)
[서버의 가벼운 백엔드(FastAPI 등)]가 프롬프트 수신
        │
        ▼
[백엔드가 claude -p "<프롬프트>" 프로세스를 서브프로세스로 실행]
        │
        ▼
[실행 완료된 텍스트 결과(또는 에러 로그)를 메신저 API/웹훅으로 발송]
```

이 구조를 쓰면 복잡한 클라이언트 수정 없이도, 메신저를 통해 서버 로컬에 설치된 Claude Code 에이전트를 원격으로 지휘할 수 있다.

### 1.2 핵심 CLI 플래그

| 플래그 / 옵션 | 역할 |
|---|---|
| `-p "<프롬프트>"` | Print/Headless 모드. 대화형 TUI 창을 띄우지 않고 텍스트 명령만 주입 |
| `--output-format json` | stdout을 JSON으로 고정 → 본문(`result`)과 `session_id`를 파싱 가능 |
| `--output-format stream-json` | 줄 단위(NDJSON) 실시간 스트리밍 출력. **`-p`와 함께 쓸 때는 `--verbose`가 필수** (미지정 시 즉시 에러) |
| `--include-partial-messages` | stream-json에 `text_delta`/`thinking_delta` 토큰 단위 이벤트를 포함 (실시간 타이핑 효과에 필요) |
| `--input-format stream-json` | stdin도 JSON 규격으로 받는다. 단, §8 실측상 헤드리스 권한 승인 개입 지점은 아니다 |
| `--resume <session_id>` | 저장된 세션 트랜스크립트를 복원해 대화 연결 |
| `--continue` / `-c` | 특정 디렉토리에서 가장 최근 세션을 바로 이어감 |
| `--model <모델명>` | 대상 모델 지정 (예: Ollama Cloud의 `kimi-k2.7-code:cloud`) |
| `--permission-mode <모드>` | 권한 정책 지정 (`default` 헤드리스 기본 — 자동 거부, `plan` 등). §8 참고 |
| `--dangerously-skip-permissions` | 파일 수정/터미널 명령의 사용자 확인(Y/n)을 건너뛰고 자동 승인 |
| `--allowedTools "Bash,Read,Edit"` | 무인 실행 시 특정 도구만 자동 승인 (상황에 따라 skip-permissions 대용) |
| `--directory <경로>` | 작업 디렉토리 고정. 세션 히스토리가 작업 디렉토리에 바인딩되므로 사실상 필수 |

> **⚠️ 실측 정정 (CLI 2.1.109)**: 초안에 있던 `--max-turns` 플래그는 이 버전 CLI에 존재하지 않는다. 무한 루프 비용 방지는 브릿지 쪽 턴 타임아웃/최대 턴 수 제한으로 구현해야 한다.
>
> 무인 자동화 환경에서는 승인 관련 옵션(`--allowedTools` 또는 `--dangerously-skip-permissions`)을 지정하는 것이 좋다. 다만 헤드리스는 권한 프롬프트에서 멈추지(Hang) 않고 **즉시 자동 거부**하므로(§8 실측), 옵션 미지정은 멈춤이 아니라 "도구 실행이 계속 실패하는 턴"이 된다.

### 1.3 세션 유지 메커니즘

기본 실행(`claude -p "..."`)만 하면 매번 새 프로세스가 뜨고 끝나므로 무상태(Stateless)처럼 보이지만, **세션 ID 플래그를 활용하면 헤드리스 모드에서도 대화 맥락을 그대로 이어갈 수 있다.**

Claude Code는 모든 작업 내역과 파일 변경 이력을 로컬(`~/.claude/projects/...`)에 JSONL 트랜스크립트로 자동 저장한다. 이를 메신저의 채널이나 스레드 ID와 매핑하면 된다.

**첫 번째 요청 (세션 시작 및 ID 발급)** — 출력 포맷을 JSON으로 지정하면 결과 텍스트와 함께 `session_id`가 반환된다.

```bash
claude -p "GPU 0번에 bge-m3 모델 로드하는 벤치마크 스크립트 작성해줘" \
  --output-format json
```

응답 JSON 예시:

```json
{
  "result": "benchmark_bge.py 스크립트를 작성했습니다...",
  "session_id": "a1b2c3d4-e5f6-7890-abcd-1234567890ab"
}
```

**두 번째 요청 (세션 이어가기: `--resume`)** — 이전 턴에서 획득한 `session_id`를 넘기면, 이전 대화 내용, 읽었던 파일, 실행했던 셸 히스토리를 그대로 컨텍스트에 불러와서 다음 작업을 수행한다.

```bash
claude -p "아까 작성한 스크립트에서 배치 사이즈를 32에서 64로 늘려서 다시 실행해줘" \
  --resume "a1b2c3d4-e5f6-7890-abcd-1234567890ab" \
  --output-format json
```

(참고: 특정 디렉토리에서 가장 최근 세션을 바로 이을 때는 `--continue` 또는 `-c` 플래그도 지원된다.)

**메신저 연동 매핑 구조** — 메신저는 스레드(Thread) 또는 대화방(Room) 단위로 고유 식별자(`thread_id`)가 존재한다. 백엔드 브릿지 서버에서 이 ID를 키-값으로 매핑해 두기만 하면 된다.

```
[사용자 메신저 입력]
       │
       ▼ (Webhook / HTTP POST)
[백엔드 브릿지 서버]
       │
       ├── thread_id 확인
       │    ├── 신규 대화: 세션 매핑 없음 -> claude -p "..." 실행 후 session_id 저장
       │    └── 기존 스레드: 매핑된 session_id 있음 -> claude -p "..." --resume <session_id> 실행
       │
       ▼ (결과 파싱)
[메신저로 답변 회신]
```

### 1.4 대화 창보다 `-p`가 느리게 느껴지는 이유

단순히 기분 탓이 아니라, 대화형 TUI와 헤드리스 모드가 동작하는 방식이 다르기 때문이다.

1. **스트리밍 출력의 유무 (가장 큰 체감 요인)**
   - TUI: 토큰이 생성되자마자 화면에 바로 찍힌다. 첫 글자가 0.5~1초 만에 떠서 "빠르다"고 느껴진다.
   - `-p`: 기본적으로 전체 작업(생각 → 도구 호출 → 코드 작성 → 터미널 실행 → 최종 답변 정리)이 100% 끝날 때까지 버퍼에 모아두었다가 한 번에 출력한다. 전체 프로세스가 끝날 때까지 아무 반응이 없어 멈춰 있거나 느리게 느껴진다.

2. **프로세스 Cold Start & 환경 스캔 비용**
   - TUI: 이미 메모리에 떠 있는 상태에서 입력만 던진다.
   - `-p`: 호출할 때마다 런타임 초기화 → 로컬 설정/토큰 인증 → git 상태 확인 → CLAUDE.md 읽기를 매 턴 처음부터(Cold Boot) 다시 수행한다. 초기화 오버헤드만 매번 1~3초 소비된다.

3. **`--resume` 시 히스토리 로드 비용**
   - 디스크의 JSONL 트랜스크립트(수만~수십만 토큰)를 통째로 읽어 파싱하고, API 엔드포인트로 전송해 프롬프트 캐시를 조회/컨텍스트를 재적재(KV Cache 복원)해야 한다. 대화가 5~6턴만 넘어가도 이 과정에서 2~5초 이상 추가된다.

**체감 속도 완화책**

- 메신저 UX: 받자마자 "작업 진행 중..." 상태 메시지를 먼저 띄우고 완료 후 수정(Edit)하거나 주기적으로 갱신
- 비본질 트래픽 차단: `export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` (텔레메트리/업데이트 체크 생략으로 Cold Start 단축)
- 세션이 무거워지면 과감히 리셋: 파일 내용이 히스토리에 계속 쌓이면 `--resume`의 토큰 전송량이 폭증해 급격히 느려진다. 태스크가 일단락되면 `/reset`으로 새 세션을 여는 것이 좋다.

---

## 2. 실행 엔진 환경: DIRECT vs OLLAMA

동일한 브릿지 코드가 두 환경에서 동작하도록 하려면, 엔진을 띄우는 방식 두 가지를 모두 지원해야 한다.

- **회사 환경 (DIRECT)**: `claude` CLI를 직접 실행 (Anthropic API 또는 사내 게이트웨이)
- **집 환경 (OLLAMA)**: `ollama launch claude`로 프록시 실행 (Ollama Cloud의 kimi-k code 모델 등)

### 2.1 `ollama launch claude`의 내부 원리

`ollama launch claude`는 대화형 터미널(TUI)을 띄우는 래퍼(Wrapper) 명령이다. 내부적으로는 별다른 마법이 아니라 다음 환경변수를 세팅하고 `claude`를 실행하는 구조다.

- `ANTHROPIC_BASE_URL`: Ollama 엔드포인트 (로컬이면 `http://localhost:11434`, Ollama Cloud면 `https://ollama.com`)
- `ANTHROPIC_AUTH_TOKEN`: 인증 토큰 (로컬이면 `"ollama"`, Ollama Cloud면 발급받은 API Key)

즉, 백그라운드 스크립트에서 subprocess를 띄울 때 이 환경변수를 주입해주면 `ollama launch claude`를 띄운 것과 동일하게 로컬/클라우드 모델 기반 Headless 실행이 된다. (이 방식은 §4의 DIRECT 모드 구현에 사용된다.)

Ollama Cloud + Kimi 계열 코딩 모델의 경우:

```bash
# 스크립트를 띄우기 전 터미널에서 엔드포인트/모델명 정상 통신 여부 확인
ANTHROPIC_BASE_URL="https://ollama.com" \
ANTHROPIC_AUTH_TOKEN="your_key" \
claude -p "print('test')" --model "kimi-k-code" --dangerously-skip-permissions
```

### 2.2 `ollama launch` 경유 시 실제 조립되는 명령어 형태

`ollama launch claude` 명령은 앞부분에서 Ollama 측 환경(모델명 등)을 설정하고, **`--` 뒤에 오는 인자들을 그대로 내부 `claude` 바이너리에 전달**하는 구조로 동작한다.

**신규 세션 실행 시 (첫 메시지)** — 사용자가 "현재 디렉토리에 hello.py 만들고 실행해줘"라고 보낸 경우:

```bash
ollama launch claude --model "kimi-k-code" -- \
  -p "현재 디렉토리에 hello.py 만들고 실행해줘" \
  --output-format json \
  --dangerously-skip-permissions
```

- 작업 디렉토리(cwd): `~/claude_workspace`
- 실행 결과(stdout): `{"result": "hello.py 파일을 생성하고...", "session_id": "9f8e7d6c-..."}` 형태로 반환

**후속 질문 시 (세션 유지)** — 파이썬 딕셔너리에 저장해 둔 `session_id`가 `--resume` 뒤에 자동으로 덧붙는다.

```bash
ollama launch claude --model "kimi-k-code" -- \
  -p "방금 만든 파일에 현재 시간도 출력하게 수정해줘" \
  --output-format json \
  --dangerously-skip-permissions \
  --resume "9f8e7d6c-5b4a-3210-fedc-ba9876543210"
```

파이썬에서 cmd 리스트를 조립할 때는 `--` 구분자를 기점으로 앞뒤를 나누어 구성한다:

```python
cmd = [
    "ollama", "launch", "claude",
    "--model", "kimi-k-code",
    "--",  # 이후부터는 claude 바이너리로 전달되는 인자
    "-p", prompt,
    "--output-format", "json",
    "--dangerously-skip-permissions"
]

if session_id:
    cmd.extend(["--resume", session_id])
```

### 2.3 두 방식(직접 실행 vs `ollama launch`)의 차이

| 방식 | 특징 |
|---|---|
| `ollama launch claude --model ... -- [인자]` | 별도로 `ANTHROPIC_BASE_URL`이나 토큰 환경변수를 수동 매핑하지 않아도 Ollama CLI가 알아서 내부 프록시와 환경 세팅을 엮어준다. 일상적으로 터미널에서 쓰던 명령과 정확히 동일한 라이프사이클로 동작 |
| 환경변수 세팅 후 `claude` 직접 호출 | 중간 래퍼 프로세스를 거치지 않고 `claude`를 바로 띄우므로 프로세스 트리와 stdout/stderr 스트림 파이프 처리가 미세하게 더 단순 |

평소 터미널 작업을 `ollama launch claude`로 익숙하게 쓰고 있다면, `ollama launch claude --model ... --` 형태로 조립하는 것이 가장 직관적이고 안전하다.

### 2.4 Ollama(Cloud/로컬) 기반 구동 시 체크포인트

회사의 순정 Anthropic Claude와 달리 Ollama 경유 모델을 에이전트 백엔드로 쓸 때의 현실적인 차이:

- **컨텍스트 길이 (로컬 모델의 경우)**: Claude Code는 기본 시스템 프롬프트만 해도 수 K 토큰을 먹고 들어간다. Ollama 기본 세팅(2k~4k)이면 파일 몇 개 읽자마자 앞선 지시를 잊는다. Modelfile이나 실행 파라미터에서 `num_ctx`를 최소 32K~64K 이상 확보해야 에이전트 루프가 정상 동작한다. (Ollama Cloud는 이 제약이 사실상 없다.)
- **도구 호출(Tool Calling) 정확도**: 파일 수정(Edit)이나 터미널 명령 시 7B~14B급 경량 모델은 가끔 인자(JSON 스키마) 형식을 틀려 스스로 에러를 내기도 한다. VRAM 여유가 된다면 Qwen2.5-Coder 계열(14B or 32B)을 물렸을 때 Claude Code와의 합이 가장 안정적이다. Kimi 계열은 긴 문맥 파악과 코딩 능력이 우수해 Claude Code의 파일 편집 및 터미널 도구 호출 포맷을 잘 준수한다.
- **타임아웃**: 로컬 추론은 클라우드 API보다 느릴 수 있으므로, 브릿지 스크립트에서 `asyncio.wait_for`를 쓸 경우 타임아웃을 넉넉히(2~3분 이상) 잡는다.
- **로컬 리소스 부담 (Cloud 모델의 경우)**: 무거운 LLM 연산은 Ollama Cloud가 처리하므로, 집 PC는 코드 파일 저장과 터미널 명령 실행만 전담해 팬 소음/GPU 부하 없이 동작한다.

---

# Part 2 — 최소 구현: 메신저 브릿지

## 3. 텔레그램 브릿지 최소 구현

집에서 개인 테스트를 진행할 때 텔레그램 + Claude Code CLI 조합이 가장 빠르고 간편하다. 텔레그램 봇 토큰 발급이 1분 만에 끝나고, 웹훅 서버(공인 IP/도메인) 없이도 **롱 폴링(Long Polling)** 방식으로 로컬 PC/서버에서 즉시 메시지를 받아올 수 있기 때문이다.

### 3.1 사전 준비

1. **텔레그램 봇 생성**: 텔레그램에서 `@BotFather` 검색 후 대화 시작 → `/newbot` 입력 후 이름/username 설정 → 발급되는 HTTP API Token 복사
2. **내 Chat ID 확인**: `@userinfobot` 검색 후 `/start` → 본인의 고유 숫자 ID 확인 (아무나 내 서버에 명령을 내리지 못하도록 화이트리스트 검증용)
3. **라이브러리 설치**: `pip install python-telegram-bot`

### 3.2 브릿지 스크립트 v1 (`telegram_claude_bridge.py`)

스레드(대화방)별로 `session_id`를 메모리에 저장해 문맥을 이어가며(Session Resume) 백그라운드에서 `claude -p`를 비동기 실행하는 구조다.

```python
import os
import json
import asyncio
import subprocess
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- 설정 ---
TELEGRAM_BOT_TOKEN = "여기에_봇파더에게_받은_토큰_입력"
ALLOWED_USER_ID = 123456789  # 본인의 Telegram User ID (정수형)
BASE_WORKSPACE = os.path.expanduser("~/claude_workspace")  # 작업 디렉토리

os.makedirs(BASE_WORKSPACE, exist_ok=True)

# 텔레그램 chat_id별 Claude Code session_id 저장소 (In-Memory)
chat_sessions = {}

async def execute_claude(prompt: str, session_id: str = None) -> tuple[str, str]:
    """Claude CLI를 headless 모드로 실행하고 결과와 session_id를 반환"""
    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "json",
        "--dangerously-skip-permissions"  # 무인 자동 실행 필수 플래그
    ]
    
    if session_id:
        cmd.extend(["--resume", session_id])

    # 비동기로 subprocess 실행
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=BASE_WORKSPACE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        error_msg = stderr.decode().strip() or "알 수 없는 에러가 발생했습니다."
        return f"실행 오류:\n```\n{error_msg}\n```", session_id

    try:
        data = json.loads(stdout.decode())
        result_text = data.get("result", "(결과 없음)")
        new_session_id = data.get("session_id", session_id)
        return result_text, new_session_id
    except json.JSONDecodeError:
        # JSON 포맷 파싱 실패 시 일반 텍스트 반환
        return stdout.decode().strip(), session_id

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 보안: 본인 계정 메시지만 허용
    if update.effective_user.id != ALLOWED_USER_ID:
        await update.message.reply_text("접근 권한이 없습니다.")
        return

    user_text = update.message.text.strip()
    chat_id = update.effective_chat.id

    # 특수 커맨드: 세션 초기화
    if user_text.lower() in ["/reset", "리셋", "새 세션"]:
        chat_sessions.pop(chat_id, None)
        await update.message.reply_text("Claude 세션이 초기화되었습니다. 새로운 맥락으로 시작합니다.")
        return

    # 대기 상태 알림
    status_msg = await update.message.reply_text("작업 수행 중... (코드 생성 및 터미널 실행)")
    
    current_session = chat_sessions.get(chat_id)
    
    # Claude CLI 실행
    response_text, new_session = await execute_claude(user_text, current_session)
    chat_sessions[chat_id] = new_session

    # 텔레그램 메시지 길이 제한(4096자) 대응 분할 전송
    await status_msg.delete()
    if len(response_text) > 4000:
        for i in range(0, len(response_text), 4000):
            await update.message.reply_text(response_text[i:i+4000])
    else:
        await update.message.reply_text(response_text)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Regex(r"^/(reset|start)$"), handle_message))
    
    print("텔레그램 Claude 브릿지 봇이 실행되었습니다. 폴링 시작...")
    app.run_polling()
```

### 3.3 테스트 진행 순서

1. 터미널에서 스크립트 실행: `python telegram_claude_bridge.py`
2. 스마트폰 텔레그램 앱에서 생성한 봇에게 메시지 전송
   - 1차 질의: "현재 디렉토리에 hello.py 만들고 실행한 결과 알려줘" → 파일 생성 + 실행 결과 확인
   - 2차 질의 (세션 유지 확인): "방금 만든 hello.py에 현재 시간도 출력하도록 고쳐서 다시 돌려봐"
   - 세션 리셋: `/reset` 입력 시 이전 작업 기록을 잊고 새 태스크 시작

이 프로토타입으로 세션 유지 흐름, 실행 지연 시간, 텍스트 분할 출력을 체감해 보면, 향후 회사 환경의 메신저(Teams, m-chat)와 사내 도구(cline-sr)로 확장할 때 백엔드 구조를 그대로 재활용할 수 있다.

---

## 4. 통합 브릿지: `agent_bridge.py` (이중 모드)

설정 플래그(`EXEC_MODE`) 하나로 회사 환경(Claude CLI 직접 실행)과 집 환경(`ollama launch claude`)을 전환할 수 있는 통합 브릿지다.

```python
import os
import json
import asyncio
import subprocess
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# ==============================================================================
# 1. 실행 환경 모드 설정
# ==============================================================================
# "OLLAMA" : 집 환경 (ollama launch claude 프록시 실행)
# "DIRECT" : 회사 환경 (claude CLI 직접 실행 - Anthropic API 또는 사내 게이트웨이)
EXEC_MODE = "OLLAMA"

# ==============================================================================
# 2. 공통 및 환경별 세부 설정
# ==============================================================================
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
ALLOWED_USER_ID = 123456789  # 본인의 Telegram 숫자 ID (@userinfobot 확인)
BASE_WORKSPACE = os.path.expanduser("~/claude_workspace")

# 집 환경 (OLLAMA) 설정
OLLAMA_MODEL = "kimi-k-code"

# 회사 환경 (DIRECT) 설정 (필요 시 사내 프록시/API 키 입력)
DIRECT_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DIRECT_BASE_URL = ""  # 사내 게이트웨이가 있는 경우 지정 (예: "http://internal-proxy:8080")

os.makedirs(BASE_WORKSPACE, exist_ok=True)
chat_sessions = {}

# ==============================================================================
# 3. CLI 명령어 및 환경변수 조립
# ==============================================================================
def build_execution_params(prompt: str, session_id: str = None) -> tuple[list[str], dict]:
    """모드에 따라 OS 명령어 리스트와 실행 환경변수를 동적으로 생성"""
    env = os.environ.copy()
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

    # Claude CLI 고유 인자 (공통)
    claude_args = [
        "-p", prompt,
        "--output-format", "json",
        "--dangerously-skip-permissions"
    ]
    if session_id:
        claude_args.extend(["--resume", session_id])

    if EXEC_MODE.upper() == "OLLAMA":
        # 집 환경: ollama launch claude --model <model> -- [인자]
        cmd = [
            "ollama", "launch", "claude",
            "--model", OLLAMA_MODEL,
            "--"  # 이후부터는 claude 바이너리로 전달되는 인자
        ] + claude_args

    else:
        # 회사 환경: claude [인자]
        cmd = ["claude"] + claude_args
        if DIRECT_ANTHROPIC_API_KEY:
            env["ANTHROPIC_API_KEY"] = DIRECT_ANTHROPIC_API_KEY
        if DIRECT_BASE_URL:
            env["ANTHROPIC_BASE_URL"] = DIRECT_BASE_URL

    return cmd, env

# ==============================================================================
# 4. 프로세스 실행 및 세션 처리
# ==============================================================================
async def execute_agent(prompt: str, session_id: str = None) -> tuple[str, str]:
    cmd, env = build_execution_params(prompt, session_id)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=BASE_WORKSPACE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        err = stderr.decode().strip() or "알 수 없는 에러가 발생했습니다."
        return f"실행 오류 (Code {process.returncode}):\n```\n{err}\n```", session_id

    raw_output = stdout.decode().strip()
    try:
        data = json.loads(raw_output)
        result_text = data.get("result", raw_output)
        new_session_id = data.get("session_id", session_id)
        return result_text, new_session_id
    except json.JSONDecodeError:
        # JSON 포맷이 아니거나 TUI 잔여 텍스트가 섞인 경우 원문 반환
        return raw_output, session_id

# ==============================================================================
# 5. 텔레그램 핸들러
# ==============================================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        await update.message.reply_text("인가되지 않은 사용자입니다.")
        return

    user_text = update.message.text.strip()
    chat_id = update.effective_chat.id

    # 세션 초기화 커맨드
    if user_text.lower() in ["/reset", "리셋", "초기화"]:
        chat_sessions.pop(chat_id, None)
        await update.message.reply_text("세션이 리셋되었습니다. 새로운 작업으로 시작합니다.")
        return

    status_msg = await update.message.reply_text(f"작업 진행 중... [{EXEC_MODE} 모드]")

    current_session = chat_sessions.get(chat_id)
    response_text, new_session = await execute_agent(user_text, current_session)
    chat_sessions[chat_id] = new_session

    await status_msg.delete()

    # 텔레그램 메시지 길이 제한(4096자) 방어
    if len(response_text) > 4000:
        for i in range(0, len(response_text), 4000):
            await update.message.reply_text(response_text[i:i+4000])
    else:
        await update.message.reply_text(response_text)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Regex(r"^/(reset|start)$"), handle_message))

    print(f"브릿지 실행 완료 | 모드: {EXEC_MODE} | 폴링 시작...")
    app.run_polling()
```

**주요 동작 요약**

| 상황 | 동작 |
|---|---|
| 집에서 구동 시 | `EXEC_MODE = "OLLAMA"` → `ollama launch claude --model kimi-k-code -- -p "..." --output-format json ...` 형태로 실행 |
| 회사/서버 구동 시 | `EXEC_MODE = "DIRECT"` → `claude -p "..." --output-format json ...` 형태로 실행 |
| 대화 맥락 유지 | 최초 실행 시 반환된 `session_id`를 딕셔너리에 저장, 다음 메시지부터 자동으로 `--resume <session_id>`를 붙여 연속된 파일 수정/터미널 작업을 이어감 |

---

## 5. 상호작용 유형 파싱과 UI 매핑

`claude -p`의 결과에는 단순 텍스트 외에 TUI에서 사용자에게 던지는 상호작용이 섞여 나온다. 메신저 봇으로 가져올 때 텍스트 덩어리로 뭉개지지 않도록 파싱해서 전용 UI(인라인 버튼, 확인 카드 등)로 대응해야 하는 대표적인 유형들이다.

| # | 유형 | 상황 예시 | 메신저 UI 매핑 |
|---|---|---|---|
| 1 | **도구 실행 승인 / 위험 경고** | `rm -rf`, `git reset --hard`, DB 드롭, 포트 바인딩 등 파괴적 명령 실행 전 `[y/n]` 확인 | 경고 카드 + 2단 인라인 버튼 ([승인] / [거부]). 버튼 클릭 시 실행 또는 중단 인터럽트 처리 |
| 2 | **단일/다중 선택지** | "A 방식(FastAPI)과 B 방식(Celery) 중 무엇으로 구현할까요?" | 텔레그램 `InlineKeyboardMarkup`으로 선택지를 버튼 렌더링. 누르면 해당 텍스트를 다음 턴 프롬프트로 전송 |
| 3 | **자유 형식 추가 입력 요청** | API 엔드포인트 주소, 포트 번호, 테스트 경로 등 누락 파라미터 질의 | `ForceReply`(답장 강제) 인터페이스로 다음 텍스트 입력을 파라미터 값으로 직접 캡처 |
| 4 | **코드 변경점 승인 (Diff/Patch)** | 대규모 파일 수정/리포팅 직전 TUI의 Git Diff 뷰어 | 파일 요약(+12, -4) 접기/펼치기 블록 또는 구문 강조 Markdown 렌더링 + [변경 적용] / [수정 요구] / [취소] 버튼 |
| 5 | **계획 수립 및 체크리스트** | 멀티 스텝 리팩토링 전 "다음 순서로 진행하겠습니다" 로드맵 | 메시지를 실시간 수정(Edit)하며 진행 단계 체크 표시를 갱신하는 진행 상황 카드 |

**헤드리스 파이프라인에서의 현실적 처리 팁 (실측 기준 — §8 참고)**

- `--output-format stream-json`(+ `--verbose` 필수)을 사용하면 Claude가 어떤 도구를 호출하려고 했는지(`tool_use`), 그 결과가 무엇인지(`tool_result`)가 이벤트 스트림으로 실시간 들어온다.
- **1번(도구 실행 승인)은 헤드리스에서 [승인/거부] 버튼 매핑이 불가능하다.** 실측상 권한 요청은 hold되지 않고 즉시 자동 거부되며, `tool_result.is_error=true`와 `result.permission_denials`로만 기록된다. UI는 "거부 사실 카드 + 진행 원환이면 `--resume` 재시도"로 대응한다.
- **완전 무인 실행 모드**: `--dangerously-skip-permissions`로 1번을 자동 통과시키고, 2번(선택지) 질문은 결과 텍스트에서 `1. ... / 2. ...` 정규식 매칭으로 추출해 메신저 버튼으로 변환. 버튼 콜백은 해당 텍스트를 다음 턴 프롬프트로 `--resume`과 함께 전송하면 된다.
- **3번(자유 입력)도 동일 원리**: 다음 턴 프롬프트로 값 자체를 전송하면 세션이 이어진다.

---

## 6. JSON 출력으로 커스텀 앱/UI 만들기

`--output-format json`을 쓰면 Claude Code는 단순한 CLI 유틸리티를 넘어 **백엔드 실행 엔진(Core Engine)으로 완전히 추상화**된다. 터미널에 갇힐 필요 없이 웹 대시보드, 일렉트론 데스크톱 앱, 모바일 PWA 등 나만의 독립된 UI를 얹을 수 있다.

### 6.1 JSON 출력에 담기는 데이터 구조 (실측)

`--output-format stream-json --verbose`로 받는 NDJSON의 실측 이벤트 계층은 다음과 같다 (CLI 2.1.109).

```jsonc
// 1) system/init — 턴 시작, 세션/모델/권한 모드 확정
{"type": "system", "subtype": "init", "session_id": "3ce4bb2a-...",
 "model": "glm-5.3-flash:cloud", "permissionMode": "default", "tools": ["Task", "Bash", "..."]}

// 2) stream_event — Anthropic 스트리밍 이벤트 래퍼 (message_start, content_block_start/delta/stop, message_delta/stop)
{"type": "stream_event", "event": {"type": "content_block_delta", "index": 1,
 "delta": {"type": "text_delta", "text": "OK"}}, "session_id": "3ce4bb2a-..."}
// delta.type: text_delta | thinking_delta  → 실시간 타이핑 효과

// 3) assistant — 턴 중간/최종 메시지 (thinking | text | tool_use 블록)
{"type": "assistant", "message": {"content": [
  {"type": "tool_use", "id": "call_4qhlgmq8", "name": "Write", "input": {"file_path": "...", "content": "hello"}}
]}, "session_id": "1d653acd-..."}

// 4) user — 도구 실행 결과 (권한 거부 시 is_error: true, §8 참고)
{"type": "user", "message": {"content": [
  {"type": "tool_result", "tool_use_id": "call_4qhlgmq8", "is_error": false, "content": "..."}
]}, "session_id": "1d653acd-..."}

// 5) result — 턴 최종 결과 + 메트릭스
{"type": "result", "subtype": "success", "is_error": false, "num_turns": 2,
 "result": "PostgreSQL 마이그레이션 스크립트를 작성했습니다...",
 "total_cost_usd": 0.25381, "duration_ms": 4144,
 "session_id": "1d653acd-...", "permission_denials": []}
```

이 중 UI에 매핑할 핵심은 `text_delta`(실시간 텍스트), `thinking_delta`(추론 과정), `tool_use`/`tool_result`(도구 카드), `result`(비용·시간·세션 ID) 다섯 종류다. workbench의 `parser.py`가 바로 이 정규화를 담당한다.

### 6.2 커스텀 앱 아키텍처

```
[클라이언트 UI (Web / Mobile / Electron)]
       │   ▲
       │   │  JSON 데이터 (상태, 선택지, 토큰 비용, Diff 등)
       ▼   │
[경량 API 서버 (Python FastAPI / Node.js)]
       │   ▲
       │   │  stdin / stdout (CLI headless 호출)
       ▼   │
[Claude Code CLI Core Engine]
```

### 6.3 커스텀 앱에서 구현할 수 있는 차별화된 UI

TUI 터미널에서 표현하기 어려운 인터랙션을 자유롭게 넣을 수 있다.

- **원클릭 액션 버튼 카드**: 정규식/파싱 로직으로 `1. 옵션 A, 2. 옵션 B` 패턴을 긁어내 카드형 버튼으로 렌더링. 모바일에서 타이핑 없이 탭 한 번으로 다음 작업 진행
- **시각적 Git Diff 뷰어**: 터미널의 깨지기 쉬운 텍스트 Diff 대신 웹의 Monaco Editor나 구문 강조 라이브러리로 좌/우 분할(Side-by-side) 표시
- **실시간 토큰/비용 게이지**: 매 턴 누적되는 `cost_usd`와 토큰 소비량을 상단 상태바에 프로그레스 바/숫자로 실시간 표시
- **서브 에이전트 트리 맵**: 백그라운드 하위 태스크의 진행 상태를 메인 세션 아래 브랜치가 뻗어나가는 트리/타임라인으로 시각화

### 6.4 구현 접근 방식

- **가장 빠른 프로토타입**: FastAPI + Streamlit 또는 Vue/React + Webhook. 폼 입력창과 결과 카드 몇 개만 두면 반나절 만에 동작하는 웹 대시보드가 나온다.
- **모바일 중심 (PWA)**: 스마트폰 브라우저 '홈 화면에 추가'를 지원하는 PWA로 만들면, 텔레그램보다 훨씬 커스텀 버튼과 상태 뷰어가 미려한 전용 모바일 바이브 코딩 리모컨이 완성된다.

---

# Part 3 — 견고한 설계

## 7. 어댑터 패턴으로 엔진 추상화

UI/메신저(프레젠테이션)와 WOL/하드웨어 제어(인프라)를 에이전트 실행 엔진과 완전히 격리하고, 에이전트 계층을 `BaseAgentAdapter` 인터페이스로 추상화한다. 향후 Anthropic이 공식 WebSocket/gRPC API를 내놓든, 로컬 Hermes CLI를 쓰든, Ollama를 쓰든 **어댑터 클래스 하나만 갈아 끼우면** 전체 파이프라인(TUI, 텔레그램, 세션 라우팅)은 한 줄도 수정할 필요가 없는 구조다.

### 7.1 시스템 레이어 아키텍처

```
[ Presentation Layer ]      Telegram Bot / Textual TUI / Webhook
                                      │
                                      ▼
[ Core Orchestrator  ]      Session Router / Flow Control / State Machine
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
[ Infrastructure Ops ]   WOL / Suspend / VRAM     [ Agent Interface ] (BaseAgentAdapter)
                         System Controller                 │
                                      ┌────────────────────┼────────────────────┐
                                      ▼                    ▼                    ▼
                             ClaudeCliAdapter     ClaudeOfficialSdkAdapter  HermesAgentAdapter
                             (Current: -p JSON)   (Future: Official API)    (Local/Ollama)
```

### 7.2 표준 데이터 규격 및 인터페이스 정의

엔진마다 다른 포맷을 표준 데이터 클래스로 변환(Normalize)한다.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator, List, Optional

class InteractionType(str, Enum):
    TEXT = "text"                 # 일반 텍스트 답변
    CHOICE = "choice"             # 사용자 선택지 (버튼 렌더링용)
    CONFIRM = "confirm"           # 위험 명령 실행 승인 (Y/N)
    ERROR = "error"               # 실행 에러

@dataclass
class AgentEvent:
    event_type: InteractionType
    content: str
    session_id: str
    options: List[str] = field(default_factory=list)  # 선택지 목록 (예: ["1. Docker", "2. SQLite"])
    cost_usd: Optional[float] = None
    raw_payload: Optional[dict] = None

class BaseAgentAdapter(ABC):
    """모든 에이전트 엔진이 반드시 구현해야 하는 공통 규격"""

    @abstractmethod
    async def send_message(
        self, prompt: str, session_id: Optional[str] = None
    ) -> AsyncGenerator[AgentEvent, None]:
        """메시지를 전송하고 정규화된 이벤트를 스트리밍/반환"""
        pass

    @abstractmethod
    async def abort(self, session_id: str) -> bool:
        """실행 중인 작업 중단"""
        pass
```

### 7.3 어댑터 구현체

**① 현재 CLI 기반 어댑터 (`ClaudeCliAdapter`)** — CLI의 `-p` 및 JSON 출력을 파싱해 표준 `AgentEvent`로 변환한다.

```python
import asyncio
import json
import re

class ClaudeCliAdapter(BaseAgentAdapter):
    def __init__(self, workspace_cwd: str = "./workspace"):
        self.workspace_cwd = workspace_cwd

    async def send_message(
        self, prompt: str, session_id: Optional[str] = None
    ) -> AsyncGenerator[AgentEvent, None]:
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions"]
        if session_id:
            cmd.extend(["--resume", session_id])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.workspace_cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout.decode())

        res_text = data.get("result", "")
        new_session_id = data.get("session_id", session_id)
        cost = data.get("cost_usd", 0.0)

        # 1. 2. 3. 형태의 선택지 패턴 감지
        choices = re.findall(r"^\d+\.\s+(.+)$", res_text, re.MULTILINE)
        if choices:
            yield AgentEvent(
                event_type=InteractionType.CHOICE,
                content=res_text,
                session_id=new_session_id,
                options=choices,
                cost_usd=cost
            )
        else:
            yield AgentEvent(
                event_type=InteractionType.TEXT,
                content=res_text,
                session_id=new_session_id,
                cost_usd=cost
            )

    async def abort(self, session_id: str) -> bool:
        # 서브프로세스 SIGTERM 처리 로직
        return True
```

**② 추후 공식 API 등장 시 교체할 어댑터 (`ClaudeOfficialSdkAdapter`)** — 나중에 Anthropic에서 공식 API를 내놓으면 이 클래스 하나만 추가하면 된다.

```python
class ClaudeOfficialSdkAdapter(BaseAgentAdapter):
    def __init__(self, api_key: str):
        self.api_key = api_key
        # self.client = OfficialClaudeSdk(api_key=api_key)

    async def send_message(
        self, prompt: str, session_id: Optional[str] = None
    ) -> AsyncGenerator[AgentEvent, None]:
        # 가상의 공식 스트리밍 SDK 호출
        # async for chunk in self.client.agent.stream(prompt=prompt, session_id=session_id):
        #     yield AgentEvent(...)
        pass

    async def abort(self, session_id: str) -> bool:
        pass
```

### 7.4 의존성 주입(DI) 기반 Core Orchestrator

중계 코어는 구체적인 클래스가 아니라 `BaseAgentAdapter` 인터페이스에만 의존한다. 환경 변수나 설정(config.yaml)에 따라 엔진을 자유롭게 스왑할 수 있다.

```python
class AgentOrchestrator:
    def __init__(self, adapter: BaseAgentAdapter):
        self.adapter = adapter  # 런타임에 주입되는 어댑터

    async def handle_user_request(self, user_msg: str, session_id: Optional[str]):
        async for event in self.adapter.send_message(user_msg, session_id):
            if event.event_type == InteractionType.CHOICE:
                # 텔레그램 인라인 키보드나 TUI 버튼으로 렌더링하도록 뷰 레이어에 위임
                print(f"[UI RENDER BUTTONS]: {event.options}")
            elif event.event_type == InteractionType.TEXT:
                print(f"[UI RENDER TEXT]: {event.content}")

            if event.cost_usd:
                print(f"[STATUS BAR METRIC]: 비용 ${event.cost_usd:.4f}")
```

### 7.5 이 설계의 실질적 이점

- **제로 리팩토링**: 공식 API가 나오면 `ClaudeOfficialSdkAdapter`를 작성하고, 주입하는 인스턴스를 `AgentOrchestrator(adapter=ClaudeOfficialSdkAdapter())`로 1줄만 바꾸면 끝난다.
- **환경별 즉시 스왑**: 회사 PC는 `ClaudeCliAdapter` (인증 세션 직결), 집 PC는 `HermesOllamaAdapter` (로컬 Kimi/Ollama 모델 직결).
- **테스트 용이성**: Mock 어댑터를 쉽게 만들어 하드웨어나 토큰 비용 소모 없이 TUI/텔레그램 UI 로직만 빠르게 단위 테스트할 수 있다.

### 7.6 공식 UI/API가 나오면 이 고민은 무의미해질까?

결론부터: **전혀 무의미해지지 않으며, 오히려 시스템의 핵심 경쟁력이 된다.** 빅테가 제공하는 API는 언제나 "자사 생태계 안에서의 일반적인 개발 워크플로우"에 머물기 때문이다.

Anthropic이 공식 API로 '절대' 해결해주지 않는 영역:

1. **이기종 하드웨어 및 전원 제어 (WOL/Power)**: 저전력 리눅스 머신에서 윈도우 PC를 원격으로 깨우고(WOL), 작업 후 절전 모드로 재우며, 유휴 전력을 통제하는 것은 어떤 AI 기업의 CLI API도 대신 짜주지 않는 영역이다.
2. **이종(Heterogeneous) 모델 및 에이전트 결합**: Anthropic은 자사 모델을 더 많이 쓰게 만드는 것이 비즈니스 모델이다. `ollama launch claude`로 Kimi를 물려 무료/로컬 추론을 돌리거나, Hermes와 Claude를 한 방에 묶어 토론시키는 구조는 공식 프레임워크가 적극 지원할 이유가 없다.
3. **실시간 물리 자원 관제 (GPU / Ghost VRAM)**: NVIDIA GPU의 VRAM 누수 감지, 프로세스 강제 회수, 온도 모니터링은 클라우드 AI 서비스 입장에서 '로컬 시스템의 부수적인 문제'에 불과하다.

공식 API 등장 시 변화:

| 구분 | 지금의 고민 (CLI / JSON 기반) | 공식 API 등장 시 |
|---|---|---|
| 역할 | 핵심 로직(오케스트레이션, 인프라) 설계 | 핵심 로직은 그대로 유지 |
| 변화점 | stdout 파싱, `--output-format json` 정규식 처리 | 공식 SDK/이벤트 핸들러로 래퍼만 교체 |
| 결과 | 독자적인 ChatOps / TUI 관제 시스템 | 더 안정적인 엔드포인트를 얻은 전용 관제 시스템 |

즉, "출력을 어떻게 파싱할까" 같은 파이프라인 말단 테크닉만 편해질 뿐, "메신저-WOL-GPU-다중 에이전트를 어떻게 유기적으로 엮을 것인가"라는 시스템 아키텍처 설계는 그대로 유지된다. 헤드리스 엔진을 부품(Component)으로 보고 그 위에 나만의 관제 계층(ChatOps/TUI)을 얹는 구조를 설계해 두면, 엔진이 바뀌든 인터페이스가 바뀌든 실행 환경이 바뀌든 가운데의 오케스트레이션 코어는 그대로 재사용된다.

---

## 8. 안전 가드레일: 명령어 가로채기

`claude -p "..." --output-format json`으로 실행하고 `proc.communicate()`로 프로세스가 끝나길 기다리면, **이미 모든 위험한 명령이 실행된 뒤의 결과만 받게 된다.** 프로세스 종료 후 파싱 방식으로는 중간 차단이 불가능하다.

> **⚠️ 실측 정정 (CLI 2.1.109 기준, 본 가이드 작성 직후 직접 검증)**
> 초안에서는 "헤드리스 모드에서 권한 승인 요청이 NDJSON 이벤트로 나오고 stdin으로 승인/거부를 밀어넣으면 보류(Hold)된다"고 했지만, 실측 결과 **그렇지 않다.** `--input-format stream-json`으로 실행해도 승인 요청 이벤트(`control_request`)는 관측되지 않고, 권한이 필요한 도구는 **즉시 자동 거부**된다. 관측되는 것은:
> 1. `assistant` 이벤트로 `tool_use`(예: Write)가 선언됨
> 2. 이어지는 `user` 이벤트의 `tool_result`가 `is_error: true`로 즉시 반환됨:
>    `"Claude requested permissions to write to ..., but you haven't granted it yet."`
> 3. `result` 이벤트의 `permission_denials` 배열에 거부 내역이 기록됨
>
> 즉 **헤드리스 CLI 수준에서 "승인 대기 후 승인"은 불가능**하며, 가드레일은 "자동 거부로 막고 → 거부 사실을 UI에 보여주고 → `--resume`으로 이어서 진행"하는 구조로 재설계해야 한다. (§8.1)

### 8.1 방법 1(재설계): 자동 거부 + 거부 표시 + `--resume` 이어가기 (실측 기반)

헤드리스에서 실제로 동작하는 가드레일은 두 모드의 토글이다.

| 모드 | 플래그 | 동작 | 용도 |
|---|---|---|---|
| **가드레일 모드** | `--permission-mode default` | 권한 필요한 도구가 나오면 **자동 거부** → `tool_result.is_error=true` + `result.permission_denials` 로 기록 → 턴은 정상 종료 | 기본값. 무단 파일 수정/실행 원천 차단 |
| **무인 모드** | `--dangerously-skip-permissions` | 모든 도구 자동 승인 | 개인 워크스테이션 등 신뢰 환경의 백그라운드 실행 |

핵심은 **거부가 "멈춤"이 아니라 "에러 응답"으로 온다**는 점이다. 브릿지는 이걸 감지해 사용자에게 보여주고, 사용자가 진행을 원하면 권한 정책을 바꾼 뒤 `--resume`으로 같은 세션을 이어가면 된다.

**실측 스키마 (workbench 덤프 기준, 발췌)**

```jsonc
// assistant 이벤트 — 도구 호출 선언
{"type": "assistant", "message": {"content": [
  {"type": "tool_use", "id": "call_4qhlgmq8", "name": "Write",
   "input": {"file_path": "...wb_probe.txt", "content": "hello"}}
], "...": "..."}, "session_id": "1d653acd-..."}

// user 이벤트 — 즉시 자동 거부 (hold 없음, 승인 이벤트 없음)
{"type": "user", "message": {"content": [
  {"type": "tool_result", "tool_use_id": "call_4qhlgmq8", "is_error": true,
   "content": "Claude requested permissions to write to ..., but you haven't granted it yet."}
]}, "session_id": "1d653acd-..."}

// result 이벤트 — 거부 내역 누적 기록
{"type": "result", "subtype": "success", "is_error": false,
 "permission_denials": [{"tool_name": "Write", "tool_use_id": "call_4qhlgmq8", "...": "..."}],
 "total_cost_usd": 0.25381, "session_id": "1d653acd-..."}
```

**실측 기반 가드레일 처리 코드 (`parser.py` + `server.py`, workbench에서 동작 검증 완료)**:

```python
# parser.py — 정규화: tool_result의 is_error를 그대로 전달
if block.get("type") == "tool_result":
    return {"event": "tool_result", "session_id": sid,
            "data": {"tool_use_id": block.get("tool_use_id", ""),
                     "content": content or "",
                     "is_error": block.get("is_error", False)}}

# server.py — 모드 토글 (UI 체크박스와 연결)
tail.append("--dangerously-skip-permissions") if skip_permissions \
    else tail += ["--permission-mode", "default"]
```

UI(워크벤치 index.html)는 `tool_result.is_error=true`면 붉은 카드로 표시하고, `result.permission_denials`를 확인해 "거부된 도구: Write — 권한 스킵 후 재시도?" 같은 후속 액션을 제공한다.

**readline() 실시간 파싱 자체는 여전히 유효하다.** `communicate()`는 프로세스 종료까지 블로킹되지만, `async for raw_line in proc.stdout`은 이벤트가 도착하는 즉시 풀린다. 다만 그 용도는 "승인 개입"이 아니라 **실시간 토큰 스트리밍(text_delta/thinking_delta), 도구 진행 상황 표시, 비용 집계**다. workbench(`server.py`의 `TurnRunner.run_turn`)가 바로 이 구조다.

### 8.2 방법 2: OS 레벨 가짜 래퍼(Shim)를 통한 하이재킹 (환경 무관 방식)

§8.1에서 확인했듯 헤드리스 CLI에는 승인 개입 지점이 없다. 따라서 **무인 모드(`--dangerously-skip-permissions`)에서도 100% 차단이 필요하면 OS 레벨이 유일한 개입 지점**이 된다. Claude가 실행하는 터미널 명령어는 결국 시스템의 `bash`나 개별 바이너리(`rm`, `git`)를 호출한다는 점을 이용한다.

**① 가짜 git 래퍼(Shim) 생성** — `~/.safe-bin/git` 스크립트를 만들고 실행 권한을 준다:

```bash
#!/bin/bash
# ~/.safe-bin/git

# 파라미터에 '--force'나 '-f'가 들어있는지 검사
if [[ "$*" =~ "--force" ]] || [[ "$*" =~ "push -f" ]]; then
    # 파이썬 가드레일 서버로 승인 확인 웹훅 전송 (curl)
    RESPONSE=$(curl -s "http://localhost:8000/check-permission?cmd=git_$*")

    if [ "$RESPONSE" != "APPROVED" ]; then
        echo "[가드레일 차단] 원격 승인이 거부되었거나 타임아웃되었습니다." >&2
        exit 1
    fi
fi

# 위험하지 않거나 승인된 경우 원래의 진짜 git 실행
exec /usr/bin/git "$@"
```

**② Claude 실행 시 PATH 최우선 순위 부여** — 파이썬에서 Claude CLI를 띄울 때 환경변수의 PATH 맨 앞에 이 가짜 디렉토리를 끼워 넣는다:

```python
custom_env = os.environ.copy()
custom_env["PATH"] = f"/home/user/.safe-bin:{custom_env['PATH']}"

# Claude는 자기가 시스템 git을 부른다고 생각하지만, 가짜 래퍼가 먼저 실행됨
proc = await asyncio.create_subprocess_exec(
    "claude", "-p", user_prompt,
    env=custom_env,
    ...
)
```

이 방식을 쓰면 Claude가 아무리 무인(`--dangerously-skip-permissions`)으로 명령을 쏟아내도, 위험한 명령어가 OS 셸에 닿는 순간 래퍼 스크립트가 실행을 멈추고 텔레그램 승인이 떨어질 때까지 블로킹된다.

**요약**: 단순 `proc.communicate()`는 작업이 다 끝난 뒤의 결과만 받으므로 차단할 수 없다. 실측 기준 헤드리스 CLI 자체에는 승인 개입 지점이 없으므로, (1) `--permission-mode default`의 **자동 거부**를 첫 번째 방벽으로 쓰고 거부 내역(`permission_denials`)을 UI로 보여준 뒤 `--resume`으로 이어가거나, (2) 시스템 PATH 심(Shim) 래퍼를 두어 실제 명령어 바이너리 실행 직전에 웹훅으로 확인받고 넘기는 방식을 취한다.

---

## 9. 엔진 위에 얹을 수 있는 확장 레이어 5가지

Claude CLI를 '추론 및 파일 수정 엔진'으로 밑에 깔았을 때, 그 위에 얹었을 때 실질적인 가치를 만드는 상위 레이어들이다. 단순한 입출력 래퍼를 넘어 개발 워크플로우를 자동화하는 계층들이다.

### 9.1 지식 및 컨텍스트 주입 레이어 (Context & Memory Layer)

Claude CLI는 기본적으로 로컬 파일만 본다. 이 위에 개인 지식 베이스를 결합하는 레이어다.

- **개인 위키 / 옵시디언(Obsidian) 지식 연결**: 마크다운 기반 개인 노트, 프로젝트 회고, 자주 쓰는 알고리즘/명령어 스니펫을 벡터화(또는 키워드 인덱싱)해 둔다. 사용자가 모호한 요구사항을 던졌을 때 이 레이어가 먼저 노트를 검색해 "과거에 내가 작성했던 코딩 컨벤션 및 유사 트러블슈팅 사례"를 프롬프트 앞단에 주입(Context Injection)한다.
- **장기 기억(Long-term Memory) 프로필**: `--resume`은 세션이 끝나면 날아가지만, 이 레이어는 "사용자가 선호하는 라이브러리(예: FastAPI, PyTorch)", "자주 발생하는 빌드 에러 패턴"을 SQLite/Markdown에 누적 요약해 두고 세션 시작 시 시스템 프롬프트로 밀어 넣는다.

### 9.2 안전성 및 거버넌스 가드레일 레이어 (Safety & Gatekeeper Layer)

헤드리스(`--dangerously-skip-permissions`) 모드로 원격에서 돌릴 때 시스템 파괴나 보안 사고를 방지하는 방화벽 역할이다.

- **명령어 위험도 분석기 (Command Interceptor)**: Claude가 실행하려는 Bash 명령어를 사전에 가로챈다. `git push --force`, `rm -rf`, 프로덕션 DB 접근, 외부 미인가 IP 통신 등이 감지되면 즉시 실행을 홀드하고 메신저/TUI로 긴급 승인 요청(Y/N) 팝업을 띄운다. → 구현 방법은 §8 참고
- **민감 정보 마스킹 (Secret Sanitizer)**: 에이전트가 터미널 환경변수(env)를 출력하거나 설정 파일(.env, 토큰, 개인 자격 증명)을 열어볼 때, 메신저나 TUI 로그 창에 전송되기 전 정규식으로 자동 마스킹(`****`) 처리한다.

### 9.3 실시간 리소스 감시 및 조율 레이어 (Resource & Task Governor)

로컬 하드웨어(GPU, CPU, 메모리)의 상태를 보고 에이전트의 작업을 조절하는 인프라 결합 레이어다.

- **OOM / 런어웨이 프로세스 킬러**: Claude가 테스트 스크립트를 잘못 짜서 무한 루프를 돌거나 VRAM을 100% 점유해 시스템이 멈추려 할 때, 백그라운드 데몬이 이를 감지해 해당 하위 프로세스만 강제 종료(`kill -9`) 후 Claude에게 "메모리 초과로 강제 중단됨. 배치 사이즈를 줄여 재시도할 것"이라는 에러 메시지를 주입한다.
- **GPU 유휴 기반 스케줄러**: VRAM 여유 공간을 실시간 체크해, 리소스가 비어 있을 때만 코드 벤치마크나 대규모 임베딩 배치 작업을 실행하도록 큐(Queue)를 관리한다.

### 9.4 사후 처리 및 워크플로우 자동화 레이어 (Post-Execution Pipeline)

에이전트가 작업을 마친 뒤 사람이 해야 하는 반복적인 마무리 작업을 대행한다.

- **시각적 변경 보고서 자동 생성**: 작업이 끝나면 변경된 git diff를 바탕으로 "1) 수정된 핵심 로직, 2) 새로 추가된 의존성, 3) 실행된 테스트 결과"를 마크다운 리포트로 자동 빌드해 텔레그램이나 메일로 발송
- **자동 CI/CD 트리거 및 롤백**: 작업 완료 후 로컬 단위 테스트가 깨지면 스스로 `git stash` 또는 `git checkout`으로 되돌리고, 성공했을 때만 자동으로 브랜치를 따서 커밋 메시지를 생성하고 PR 초안을 생성

### 9.5 멀티모달 & 챗옵스 인터페이스 레이어 (ChatOps & Voice Interface)

텍스트 타이핑 외의 수단으로 CLI를 조작하게 만드는 레이어다.

- **음성 메모 to 코드 지시 (Voice Coding)**: 스마트폰으로 짧은 음성 메시지(STT)를 녹음해 메신저로 던지면, 정제된 개발 요구사항 프롬프트로 변환해 Claude CLI에 입력
- **스마트폰 스크린샷 기반 버그 리포팅**: UI 깨짐이나 모바일 웹 에러 화면을 캡처해서 폰으로 봇에 전송하면, 이미지를 분석해 프론트엔드 CSS/컴포넌트 수정 작업으로 연결

### 9.6 레이어 조합 추천 구성

| 순위 | 레이어 | 구현 방식 | 주는 이점 |
|---|---|---|---|
| 1단계 | 안전 가드레일 (Command Interceptor) | 파이썬 서브프로세스 훅 | 원격/무인 실행 시 안심하고 백그라운드 위임 가능 |
| 2단계 | 리소스 모니터 & OOM 킬러 | pynvml + 백그라운드 감시 루프 | GPU/VRAM 락다운 및 PC 먹통 현상 완전 방지 |
| 3단계 | 로컬 지식 베이스 주입 (Markdown RAG) | 로컬 마크다운 인덱서 | 내 코딩 스타일과 과거 노트를 기억하는 전용 비서화 |

워크플로우에서 가장 병목이 되거나 불안한 지점(무인 실행 안정성 vs 노트/히스토리 연동)부터 하나씩 계층을 올려가는 것이 좋다.

---

## 10. 멀티 에이전트 오케스트레이션

`-p`(Headless 실행)와 `--resume`(세션 유지)이 지원되면, 파이썬이나 셸 스크립트 같은 가벼운 중계기(Orchestrator)가 Agent A의 표준 출력(stdout)을 Agent B의 입력(`-p`)으로 넘겨주는 탁구(Ping-Pong) 루프를 만들 수 있다. 각 에이전트가 각자의 `session_id`를 유지하기 때문에, 서로의 역할(Role)과 전문성을 잃지 않은 채 깊이 있는 상호작용이 가능해진다. 즉, **멀티 에이전트 협업 시스템이 성립한다.**

### 10.1 에이전트 간 대화 기본 아키텍처

각 에이전트는 독립된 세션 ID를 가지며, 중계 스크립트가 턴(Turn)을 교대로 넘겨준다.

```
[Orchestrator Loop]
       │
       ├── 1. Agent A (-p "요구사항 분석해줘", session_A)
       │        └── 출력: "설계서 및 1차 코드 초안..."
       │
       ├── 2. Agent B (-p "[Agent A의 초안 리뷰해줘]", session_B)
       │        └── 출력: "VRAM 누수 위험 발견. 예외 처리 추가 필요..."
       │
       └── 3. Agent A (-p "[Agent B의 피드백 반영해줘]", session_A, --resume)
                └── 출력: "피드백 반영 완료한 최종 스크립트 작성..."
```

### 10.2 실제로 구현 가능한 패턴

1. **개발자 ↔ 코드 리뷰어 (Coder & Reviewer)**
   - Agent A (Coder): 코드를 짜고 터미널에서 실행
   - Agent B (Reviewer): A가 작성한 코드와 실행 로그를 받아 보안 취약점, 성능 병목(VRAM 효율, OOM 가능성), 코딩 컨벤션을 지적
   - 리뷰어가 "LGTM/APPROVED"를 출력할 때까지 3~4턴 자율 코드 다듬기
2. **기획/아키텍트 ↔ 실행자 (Planner & Executor)**
   - Agent A (Planner): 거시적 작업 계획을 쪼개고 요구사항 정의
   - Agent B (Executor): 한 단계씩 파일 시스템을 건드리고 라이브러리를 설치하며 구현. 에러를 만나면 A에게 상황을 보고하고, A가 우회 전략을 짜서 B에게 다시 내려줌
3. **이종 모델/도구 간 협업 (Heterogeneous Multi-Agent)**
   - Agent A (집 환경): `ollama launch claude --model kimi-k-code` (빠르고 비용 없는 추론)
   - Agent B (고성능): 순정 Claude Sonnet (고난도 로직 검증 및 최종 감사)
   - 가벼운 작업은 A가 도맡아 치고받고, A가 막히거나 최종 단계에서만 B를 호출

### 10.3 최소 구현 예시 (Python Orchestrator)

두 에이전트가 서로를 호출하며 티키타카를 주고받는 핵심 루프:

```python
import asyncio
import json

async def run_agent(agent_name: str, prompt: str, session_id: str = None) -> tuple[str, str]:
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--dangerously-skip-permissions"
    ]
    if session_id:
        cmd.extend(["--resume", session_id])

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    data = json.loads(stdout.decode())
    return data.get("result", ""), data.get("session_id")

async def agent_debate():
    # 초기 역할 부여
    prompt_coder = "너는 백엔드 개발자야. PyTorch 기반 GPU 벤치마크 스크립트 초안을 짜줘."
    prompt_reviewer = "너는 엄격한 시니어 코드 리뷰어야. 상대방 코드의 메모리 누수와 예외 처리를 검토해줘. 완벽하면 'APPROVED'라고만 해."

    # 1턴: 개발자가 초안 작성
    code_output, session_coder = await run_agent("Coder", prompt_coder)
    session_reviewer = None

    for turn in range(3):  # 최대 3턴 동안 티키타카
        print(f"\n--- [Turn {turn+1}] Reviewer 차례 ---")
        review_prompt = f"다음 코드를 리뷰해줘:\n\n{code_output}"
        review_output, session_reviewer = await run_agent(
            "Reviewer", review_prompt, session_reviewer
        )
        print(review_output)

        if "APPROVED" in review_output:
            print("\n리뷰 통과! 최종 코드가 확정되었습니다.")
            break

        print(f"\n--- [Turn {turn+1}] Coder 수정 차례 ---")
        fix_prompt = f"리뷰어 피드백이야. 코드를 수정해줘:\n\n{review_output}"
        code_output, session_coder = await run_agent(
            "Coder", fix_prompt, session_coder
        )
        print(code_output)

asyncio.run(agent_debate())
```

### 10.4 주의: 환각의 핑퐁(Echo Chamber) 방지

에이전트끼리 대화를 붙일 때 반드시 걸어야 하는 안전장치:

- **종료 조건(Break Condition) 강제**: 서로 칭찬만 주고받거나 끝없는 수정 루프에 빠질 수 있으므로, 최대 턴 수(보통 3~5회)와 특정 종료 키워드(`DONE`, `APPROVED`)를 명시
- **비용 및 토큰 누적**: 대화가 이어질수록 `--resume`으로 복원되는 컨텍스트 창이 기하급수적으로 커진다
- **진행 상황 메신저 브로드캐스트**: 턴이 끝날 때마다 텔레그램/Teams에 요약 카드를 한 줄씩 쏴주면 사람은 지켜보다가 필요할 때만 개입할 수 있다

텔레그램 한 방에 여러 에이전트를 모으는 아키텍처(봇 정책 제약 포함)는 부록 G 참고.

---

## 11. 커스텀 TUI 만들기

기본 제공 TUI가 "순수 코딩 작업자"에게 맞춰져 있다면, 커스텀 TUI를 만들면 하드웨어 제어, 다중 에이전트 관제, 모바일/원격 연동까지 한 화면에 통합된 전용 관제탑(Mission Control)을 구축할 수 있다.

### 11.1 가능해지는 일들

**① 하드웨어 및 시스템 리소스 실시간 계측 (System Ops)**
- **GPU/VRAM 실시간 미터기**: `pynvml`을 연동해 화면 상단/측면에 GPU 사용률, 실시간 VRAM 점유량, 온도, 팬 속도를 프로그레스 바로 상시 렌더링
- **유령 VRAM(Ghost VRAM) 및 좀비 프로세스 감지**: 에이전트가 돌린 파이썬 스크립트가 비정상 종료되어 VRAM을 물고 있을 때 경고 배지를 띄우고 `[F9: Kill Zombie]` 단축키 하나로 즉시 메모리 회수
- **원격 전원 상태 표시**: 타겟 머신의 전원 상태(Sleep, Awake)와 절전 타이머를 실시간 카운트다운으로 노출

**② 멀티 에이전트 분할 관제 (Multi-Agent Split View)**
- **Coder vs Reviewer 2분할 뷰**: 좌측 창은 Claude(Coder)가 실시간으로 코드를 짜고 터미널 명령을 실행하는 로그, 우측 창은 Hermes/Kimi(Reviewer)가 해당 코드를 실시간 감사하며 피드백을 다는 로그
- **서브 에이전트 트리 시각화**: 메인 에이전트가 스폰한 하위 태스크들의 진행 상태(탐색 중, 테스트 실행 중, 완료)를 좌측 트리 패널에 실시간 갱신
- **에이전트 핫스왑 단축키**: Tab이나 F1~F4 키로 백엔드 엔진을 즉시 전환 (Claude Direct ↔ Ollama Kimi ↔ Hermes)

**③ 모바일/메신저와의 양방향 상태 동기화 (Omnichannel Sync)**
- **QR 코드 기반 모바일 세션 핸드오프**: 외출 직전 TUI에서 단축키를 누르면 현재 세션 복원용 일회성 URL 또는 텔레그램 딥링크 QR 코드 생성 → 폰으로 찍고 나가면 이동 중에 텔레그램으로 대화 지속
- **메신저 메시지 실시간 미러링**: 밖에서 폰으로 지시한 내역과 에이전트의 답변이 PC 방의 TUI 로그 창에도 타임라인 형태로 스트리밍

**④ 개발자 경험(DX) 및 워크플로우 특화 기능**
- **키보드 단축키 원클릭 의사결정**: Y=제안된 Bash 명령 승인 및 실행 / N=거절 / D=전체 Diff 접기·펼치기 / S=현재 세션 내용을 마크다운 보고서로 즉시 덤프
- **인터랙티브 파라미터 튜너**: 모델 추론 옵션(Temperature, Max Tokens, 모델 프리셋)을 코드 수정 없이 슬라이더/셀렉트 박스로 실시간 조절
- **로컬 지식 베이스 원클릭 주입**: 자주 쓰는 시스템 프롬프트, 프로젝트별 가이드라인, 사전 정의된 테스트 시나리오를 단축키 팔레트(Ctrl+P)로 검색해 프롬프트 입력창에 즉시 삽입

### 11.2 공식 TUI는 오픈소스인가?

**아니다.** Claude Code의 TUI를 포함한 공식 소스코드는 독점 라이선스(Proprietary)다. npm 패키지(`@anthropic-ai/claude-code`)로 배포되지만 소스코드가 공개된 레포지토리는 없다.

다만 실제 동작 코드 분석과 대체 오픈소스 참고 두 가지로 구조를 파악할 수 있다:

- **배포된 로컬 번들 파일 분석**: 설치 위치 확인 (`which claude`, 보통 `~/.nvm/.../bin/claude` 심볼릭 링크, 실제 패키지는 `~/.nvm/versions/node/<버전>/lib/node_modules/@anthropic-ai/claude-code/`). 난독화(Minify/Bundle)되어 있지만 웹팩/esbuild 번들 형태의 자바스크립트라 내부 구현 기술과 구조를 뜯어볼 수 있다.
- **사용 기술 스택**: Claude Code의 TUI는 터미널용 React 렌더러인 **Ink (React for CLI)** 기반이다. CSS Flexbox와 유사한 Yoga layout 엔진, React의 컴포넌트 생명주기 및 훅(`useState`, `useEffect`)을 터미널 UI에 그대로 적용한 구조다.

**TUI/아키텍처 참고용 오픈소스**

| 프로젝트 | 언어 / 라이브러리 | 참고 포인트 |
|---|---|---|
| Aider | Python / prompt_toolkit, rich | CLI 코딩 에이전트의 원조. 터미널 자동완성, 멀티라인 입력, 구문 강조, 파일 변경 Diff 출력을 Python에서 가장 우아하게 구현. 파이썬 기반 커스텀 앱 제작 시 최고의 참고서 |
| OpenHands (구 OpenDevin) | Python + TypeScript(React) | 웹 UI 대시보드와 Headless REST/WebSocket API를 모두 갖춤. 에이전트 이벤트 스트림(도구 실행, 승인 대기, 비용 계산)을 프론트엔드 컴포넌트로 매핑하는 법 학습 |
| Ink 생태계 (vadimdemedes/ink) | TypeScript/React | Claude Code와 동일한 손맛의 CLI/TUI를 직접 짜려면 정석. `ink-select-input`(선택지), `ink-text-input`(텍스트 입력), `ink-spinner`(로딩) 조합으로 Claude Code 화면 구성을 1:1 재현 가능 |

### 11.3 추천 기술 스택: Python Textual

커스텀 TUI를 구현할 때 추천 도구는 Python 기반의 **Textual**이다.

- **CSS 스타일링 지원**: 웹 개발처럼 그리드/플렉스박스 레이아웃과 CSS 스타일로 터미널 UI 디자인
- **비동기(Asyncio) 네이티브**: 서브프로세스 실행, 시스템 모니터링 폴링, 텔레그램 웹훅을 백그라운드 이벤트 루프 하나로 처리
- **마우스 지원**: 터미널 환경에서도 클릭, 스크롤, 버튼 인터랙션 기본 지원

TUI 형태를 유지하고 싶다면 Textual(Python) 또는 Ink(Node.js)를, 웹/모바일 리모컨 형태로 가고 싶다면 §6처럼 `--output-format json`을 받아 React/Vue + Tailwind CSS로 모바일 친화적인 카드형 UI를 만드는 것이 낫다.

---

# 부록

## 부록 A. MS Teams API 개요 · 응용 사례 · 사내 메신저(m-chat) 연동

### A.1 Teams 관련 기능의 3가지 접근 방식

Microsoft Teams 관련 기능은 주로 Microsoft Graph API를 통해 제어하며, 목적에 따라 Incoming Webhook이나 Bot Framework를 활용한다.

1. **Microsoft Graph API (가장 범용적)**: 통합 REST API 엔드포인트(`https://graph.microsoft.com/v1.0`). 채널 생성/관리, 메시지 전송 및 조회, 팀 멤버 추가/삭제, 온라인 미팅 예약 및 통화 기록 조회, 파일 업로드 등. 인증은 Microsoft Entra ID(구 Azure AD)의 OAuth 2.0 토큰 기반 — 위임된 권한(Delegated, 로그인 사용자 권한)과 애플리케이션 권한(Application, 백그라운드 데몬/서비스)으로 나뉜다.
2. **Incoming Webhook (단순 알림용)**: 복잡한 인증 없이 특정 채널에 메시지/카드를 쏘아 올릴 때. 채널 커넥터 설정에서 Webhook URL을 생성한 뒤 JSON 페이로드로 POST. 배포 알림, 모니터링 경보 전송 등에 적합하며 Adaptive Cards 포맷으로 버튼이나 구조화된 UI를 포함할 수 있다.
3. **Azure Bot Framework (양방향 인터랙션)**: 사용자와 1:1 대화하거나 채널에서 멘션(`@bot`)을 받아 명령을 처리하고 응답하는 챗봇 구현.

### A.2 현업 응용 사례

- **CI/CD 및 인프라 알림 자동화**: 배포 승인 카드(Teams 채널에 승인 요청 → 담당자가 [승인/반려] 버튼 클릭 → CI 도구 트리거), 서버 장애 대응(모니터링 경보 + 로그 스니펫 + 버튼 하나로 로그 조회/담당자 자동 멘션)
- **팀 지식베이스 및 사내 RAG 챗봇**: 사내 기술 문서/위키 임베딩 → 채널에서 `@bot` 질의 시 문맥 파악해 답변 + 출처 링크. 채널 히스토리 요약(Graph API로 최근 일주일 논의/결정 사항 조회 후 요약 리포트)
- **회의 및 일정 자동화**: `onlineMeetings` 엔드포인트로 미팅 링크 원클릭 생성 + 참석자 초대장 발송. 미팅 종료 후 Graph API로 녹음/전사(Transcript) 데이터 수집 → 요약 엔진 → 회의록 자동 공유
- **온보딩 및 반복 워크플로우 자동화**: 신규 입사자 발생 시 프로젝트 채널 자동 초대, 환영 메시지 + 가이드 문서 링크 자동 발송, 주간 스크럼 체크인 자동 DM 후 답변 취합
- **결재 및 사내 포털 연동 대시보드**: 휴가 신청/경비 처리 결재 알림을 Teams 카드로 수신하고 승인 처리, 시스템 로그인 없이 Teams 안에서 긴급 태스크 티켓 생성 (Jira, GitHub Issues 연동)

### A.3 사내 메신저가 "Teams API 기반"이라고 들었을 때 확인할 3가지

기업용 사내 메신저는 순정 MS Teams 클라이언트를 그대로 쓰기보다, 보안(DRM, 망분리, DLP)과 사내 포털/조직도 연동을 위해 Teams의 백엔드/API를 기반으로 사내 전용 UI와 게이트웨이를 덧씌운 형태(커스텀 브랜딩 클라이언트)로 운영되는 경우가 많다.

1. **표준 MS Graph API를 직접 열어주는가?**: 순정 Teams라면 Azure/Entra ID 포털에서 App 등록 후 Client ID/Secret으로 `graph.microsoft.com`을 찌르면 된다. 하지만 대기업 환경에서는 보안 정책상 공용 Graph API 호출을 차단하고, 사내 API 게이트웨이(내부 프록시 URL)를 거쳐 특정 엔드포인트만 제한적으로 호출하도록 구성하는 경우가 일반적이다.
2. **봇(Bot) 등록 및 Webhook 허용 여부**: 채널 커넥터 메뉴에서 Webhook URL 생성이 막혀 있는지 확인. 별도의 사내 봇 승인 포털이나 관리자 승인 절차가 있는지, 내부 사설 Bot Framework 어댑터를 써야 하는지가 갈린다.
3. **망 분리 및 SSL 프록시 통신**: 서버(GX10 등)가 위치한 사내 개발망/연구망에서 해당 메신저 API 서버로의 아웃바운드(443 포트)가 허용되어 있는지, 사내 CA 인증서(Zscaler 등) 처리가 필요한지 확인.

**현실적인 연동 전략**: 최우선으로 사내 Webhook(단방향 알림)이 열려 있는지 확인 — 복잡한 OAuth 없이 발급된 URL로 JSON만 쏘면 되므로 모니터링/배치 완료 알림을 즉시 붙일 수 있다. 사내 오픈 API 포털/개발자 포털의 "메신저 연동 가이드" 위키에 전용 SDK나 내부 REST 엔드포인트 규격이 있을 가능성이 높다. 백엔드가 MS Graph 규격을 따른다면 `Authorization: Bearer <token>` 체계와 메시지 페이로드(Adaptive Cards 스키마)는 표준 규격과 동일하게 동작한다.

### A.4 웹 기반 사내 메신저(m-chat) 접근법

웹 기반 사내 메신저라면 외부 클라우드 의존적인 Teams 정식 Graph API보다 연동이 수월하고 사내망 친화적일 가능성이 높다.

- **개발자 도구(F12)로 엔드포인트 바로 확인 (가장 빠름)**: 브라우저에서 m-chat 접속 → F12 → Network 탭 → 아무 채널에 메시지 전송 → 발생하는 POST 요청(XHR/Fetch) 확인. Request URL(사내 API 서버 주소/패스), Headers(쿠키 세션인지, `Authorization: Bearer` 토큰인지, 사내 SSO 헤더인지), Payload(채널 ID, 메시지 텍스트, 멘션 포맷 등 JSON 구조)를 파악하면, GX10에서 curl이나 Python `requests`로 동일한 헤더/본문을 쏴서 5분 만에 발송 검증이 가능하다.
- **Webhook / Bot 지원 확인**: 채널 설정 메뉴에 "웹훅 추가", "봇 추가", "외부 서비스 연동" 항목이 있는지 확인. URL이 발급되면 GPU 상태 리포트, Ghost VRAM 감지 알림, 배치 완료 통보 스크립트를 즉시 붙일 수 있다.
- **양방향 연동 시**: m-chat이 웹 기반이면 실시간 수신을 위해 WebSocket 연결을 맺고 있을 확률이 높다. GX10 백엔드가 이 소켓에 클라이언트로 붙어 특정 키워드(예: `@GX10`)를 감지하고 작업을 트리거하는 방식이 가능하다. 외부 인터넷(MS Azure 등)으로 나가지 않고 사내 인트라넷 IP 대역 내에서만 HTTP/WebSocket 통신이 이루어지므로 사내 보안 정책(DLP, 망분리)에 걸릴 위험이 사실상 없다.

---

## 부록 B. GPU 서버(GX10) 특화 자동화 시나리오

ASUS Ascent GX10 워크스테이션을 팀 내 공유 인프라로 운영할 때, Teams API(Webhook/Bot/Graph API)와 결합하면 GPU 자원 모니터링, 작업 스케줄링, 팀 협업 자동화 관점에서 실용적인 시나리오를 만들 수 있다. 여러 팀원이 SSH나 컨테이너로 접속해 임베딩, 재순위화(Re-ranking), 로컬 LLM 추론/학습 작업을 돌릴 때의 병목을 해소한다.

### B.1 GPU 자원 점유 모니터링 및 실시간 알림

- **GPU 유휴/과부하 알림 (Webhook)**: `nvidia-smi`를 주기적으로 체크하는 경량 데몬(crontab 또는 systemd service)을 둔다. GPU VRAM 사용률이 장시간 90% 이상 유지되거나, 반대로 장시간 비어있을 때 Teams 채널에 Adaptive Card로 상태를 리포팅한다.
- **장기 독점 프로세스 주의 알림**: 특정 사용자의 컨테이너/프로세스가 VRAM을 점유한 채 GPU 연산율(GPU-Util)이 0%로 N시간 이상 유지되면 담당자에게 Teams 멘션 알림을 보내 자원 반환을 유도한다.

### B.2 배치/인퍼런스 작업 완료 및 에러 콜백

무거운 임베딩 빌드나 대량 데이터 전처리 작업을 걸어두고 수시로 터미널을 확인할 필요가 없게 만든다.

- **스크립트 완료 웹훅**: Python/배치 셸 스크립트 종료 시점에 Teams Incoming Webhook 호출. 실행 소요 시간, 처리된 문서/토큰 수, 에러 로그 요약을 카드 형태로 개인 DM이나 팀 채널에 전송.
- **OOM / Crash 긴급 알림**: Docker 컨테이너가 exit code 비정상(OOMKilled 등)으로 다운되었을 때 즉시 담당자에게 스택트레이스와 함께 Teams 알림 발송.

### B.3 "누가 GPU 쓰나요?" 실시간 자원 조회 ChatOps

팀원들이 터미널에 일일이 접속해 `nvidia-smi`를 쳐보지 않고도 Teams 채널에서 즉시 상태를 확인한다.

- **슬래시 커맨드/멘션 조회**: Teams에서 `@GX10-bot status` 또는 `/gpu` 입력 → 서버에서 간단한 API(FastAPI 등)를 거쳐 현재 GPU 온도, VRAM 사용 현황, 실행 중인 Docker 컨테이너 목록 및 실행자 정보를 파싱해 카드로 응답.
- **컨테이너 정리/재시작 트리거**: 좀비 컨테이나 정지된 컨테이너를 Teams 카드의 [재시작]/[정지] 버튼으로 원격 처리할 수 있도록 권한 제어형 인터랙션 추가.

### B.4 사내 RAG / 인덱싱 파이프라인 트리거 허브

GX10이 임베딩/RAG 백엔드 서버 역할을 한다면 문서 업데이트 주기를 Teams와 연동할 수 있다.

- **신규 문서 업로드 시 인덱싱 알림**: 팀 공유 저장소에 새 문서 추가 → GX10의 임베딩 파이프라인(Vector DB 인덱싱) 완료 → Teams 채널에 "OO 문서 인덱싱 완료(벡터 수: N개)" 브로드캐스트.
- **Teams 질의 봇의 백엔드로 GX10 연결**: Teams 채널에서 들어온 사내 기술 질문을 GX10에 띄워둔 서빙 엔진(vLLM / Ollama / 임베딩 서버)으로 전달해 답변을 받아 채널에 반환.

### B.5 "유령 점유(Ghost VRAM)" 탐지 및 조치 알림

GPU 환경에서 가장 흔한 문제는 "프로세스는 끝났거나 좀비 상태인데 VRAM만 24GB~80GB씩 물고 있는 현상"이다 (Jupyter 커널 방치, PyTorch OOM 후 비정상 종료 등).

- **동작 원리**: GPU Memory > 80%이지만 GPU-Util == 0%인 상태가 1시간 이상 지속되는 프로세스 감지.
- **Teams 연동**: 프로세스 소유자(UID/컨테이너 이름), 점유 VRAM 크기, PID를 Adaptive Card로 전송. [프로세스 종료 승인] 버튼을 카드에 심어, 관리자나 당사자가 클릭 한 번으로 `kill -9` 또는 컨테이너 리셋을 실행.

### B.6 가상 GPU "대기열(Queue) & 예약 릴레이" 봇

고가의 GPU 워크스테이션을 여러 명이 쓰다 보면 "지금 누구 돌리는 중인가요?", "언제 끝나요?"라는 대화가 빈번하다.

- **예약 등록**: 현재 VRAM 여유가 없어 대규모 배치(임베딩 대량 빌드, 파인튜닝)를 못 돌리는 팀원이 Teams에서 `@GPU-Bot reserve 2h` 예약 등록.
- **릴레이 알림**: 실행 중이던 작업이 끝나 VRAM이 확보되는 순간 대기자에게 Teams 멘션: "VRAM 40GB 확보되었습니다. @장기석 님의 예약 작업 순서입니다. (15분 내 미사용 시 다음 대기자에게 이관)"

### B.7 멀티 인스턴스/모델 서빙 동적 스왑 제어 (ChatOps)

로컬 LLM이나 대형 임베딩 모델(Dense/ColBERT/Re-ranker)을 항상 메모리에 올려두면 다른 팀원이 실험용 컨테이너를 띄울 자리가 부족해진다. Teams 채널에서 슬래시 명령어로 현재 로드된 모델을 내리거나 교체한다.

- `/model status` → 현재 VRAM에 올라간 서빙 모델 확인 (예: `bge-m3: 6GB`, `llama-3.1-70b: 40GB`)
- `/model unload llama-3.1-70b` → 실험용 작업 공간 확보를 위해 서빙 컨테이너 일시 중지
- `/model reload` → 실험 완료 후 기본 서빙 인스턴스 원복

### B.8 하드웨어 스로틀링 및 환경 이상 경보 (Hardware Telemetry)

워크스테이션 폼팩터는 랙마운트 전용 서버실과 달리 실내 온도, 먼지, 쿨러 이상 등으로 인한 쓰로틀링 위험이 더 크다.

- **감지 항목**: `nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks.current.graphics`
- **Teams 연동**: GPU 온도가 임계치(예: 85°C 이상)에 도달하거나, 전력 제한으로 인한 Thermal Throttling(클럭 급감)이 감지되면 채널에 긴급 적색 카드 발송. 실행 중인 배치 스크립트에 일시 정지(SIGSTOP)를 걸거나 팬 속도/팬 프로필 상태를 함께 로깅해 하드웨어 손상을 방지.

### B.9 배치 실험 '벤치마크/비용' 자동 리포팅

대량 임베딩 생성, RAG 인덱싱, 토큰 처리 벤치마크가 끝났을 때 하드웨어 효율성을 요약해 준다.

Teams 리포트 카드 예시:

```
처리 문서: 50,000건 / 총 소요 시간: 18분 24초
평균 VRAM 점유: 18.2 GB / 피크 전력: 320W
처리 속도: 1,450 chunks/sec
결과: "클라우드 API(OpenAI/Voyage 등) 대비 약 $XX 절감 효과 달성"
```

같은 환산 지표를 함께 출력해 로컬 서버 운영의 효용성을 팀에 시각화한다.

**우선순위**: 가장 빠르게 효과를 볼 수 있는 것은 B.1(nvidia-smi 기반 상태 모니터링 Webhook)이나 B.2(작업 완료/실패 콜백)다.

---

## 부록 C. "채팅창에서 코드 실행"의 한계 분석과 대안

Teams/메신저 채팅으로 코드를 넣으면 서버(GX10)에서 돌려서 결과를 주고, 길면 진행상황까지 갱신해주는 기능 — 매우 실용적으로 보이지만, 데모로 보여주기엔 화려해도 실제 개발팀 환경에 도입하면 첫 주에 신기해서 두세 번 써보고 곧바로 버려질 확률이 90% 이상이다.

### C.1 기능 구상 (참고용)

- **사용자 요청**: Teams에서 봇을 멘션하며 코드 블록 전송 (`@GX10-bot run` + Python 코드)
- **봇 수신 & 메시지 선점**: 코드를 파싱하고 고유 Job ID 발급 → 채널에 즉시 카드 응답 ("작업 실행 시작, Job #102")
- **격리 컨테이너에서 비동기 실행**: 일회용 경량 Docker 컨테이너에서 코드 실행 (GPU 패스스루)
- **진행 상황 업데이트**: stdout 출력을 가로채거나 에포크/진행률 단위로 Teams 메시지를 실시간 수정(Update)
- **결과 반환**: 실행 결과(stdout/stderr), 실행 시간, 피크 VRAM 사용량을 카드에 요약

기술적 핵심 포인트:

- **보안 및 자원 격리**: 호스트 환경 오염을 막기 위해 `--rm --gpus all --memory="8g" --network none` 등을 적용한 일회용 컨테이너에서 실행. 호스트 볼륨 마운트는 최소화(읽기 전용).
- **진행 상황 실시간 업데이트**: Bot Framework REST API는 이미 보낸 메시지의 `activityId`로 내용 수정(Update Activity)이 가능하다. 매 초 새 메시지를 보내면 도배되므로, 최초 응답 카드를 2~3초 간격으로 내용만 덮어쓰기하며 프로그레스 바나 최신 stdout 라인을 갱신.
- **하드 타임아웃**: 무한 루프(`while True: pass`)나 hang 방지를 위해 기본 실행 제한 시간(3~5분)을 두고 초과 시 SIGKILL.

프로토타입 아키텍처: Bot 인터페이스(FastAPI), 작업 큐/워커(Celery 또는 `asyncio.create_subprocess_exec`), 실행 엔진:

```bash
docker run --rm --gpus device=0 \
  --memory=16g --cpus=4 \
  -v /tmp/jobs/job_102.py:/app/run.py:ro \
  pytorch/pytorch:latest python /app/run.py
```

### C.2 도입되지 않는 현실적 이유

개발자들의 실제 작업 흐름을 고려할 때 이 기능이 외면받는 이유:

1. **채팅창 입력 환경의 치명적인 불편함**: Python은 들여쓰기가 생명인데, Teams 입력창은 Tab 키를 누르면 다음 버튼으로 포커스가 넘어가거나 서식이 깨지기 일쑤다. 개발자들은 이미 자동완성, 린팅, 디버깅을 갖춘 IDE(VS Code, Cursor, Jupyter)를 쓰고 있어 굳이 텍스트 박스에 코드를 타이핑할 이유가 없다.
2. **컨텍스트와 데이터셋 부재 (무상태의 한계)**: GPU 코드는 보통 로컬 데이터셋, 모델 가중치 파일, 전처리 파이프라인과 결합되어 돌아간다. 단일 코드 스니펫만 실행해서는 의미 있는 작업이 어렵다. 필요한 라이브러리(transformers, 특정 버전 torch, 커스텀 모듈)가 컨테이너에 없으면 매번 설치 코드를 넣어야 해서 피로도가 급증한다.
3. **"진행 상황 모니터링" 도구로서의 비효율**: 작업이 길어지면 수십 줄의 에포크 로그, 배치 진행률, 텐서보드 지표를 봐야 한다. Teams 카드의 제한된 크기에서 이를 갱신하며 보는 것은 터미널의 `watch`나 대시보드에 비해 가독성이 현저히 떨어진다. 돌리다가 Ctrl+C로 멈추거나 파라미터를 살짝 바꿔 다시 돌리는 빠른 피드백 루프도 어렵다.
4. **사내 보안 및 권한 이슈**: Teams 채널을 통해 서버 내부에서 임의의 코드가 실행된다는 점 자체가(RCE) 인프라/보안 담당자 관점에서 매우 꺼려지는 구조다.

### C.3 그렇다면 팀원들이 '진짜로' 쓰는 방향

"Teams에서 코드를 직접 실행하는 것"은 비효율적이지만, "개발자가 터미널/IDE에서 돌려놓은 작업을 Teams가 케어해 주는 것"은 정반대로 수요가 크다.

- **CLI/스크립트 한 줄 연동 알림 (Push 모델)**: 채팅창에 코드를 치게 하는 대신, 팀원들이 자기 터미널에서 실행할 때 웹훅 플래그 하나만 붙이게 하는 방식:

```bash
# 작업 끝나면 Teams로 성공/실패와 수행 시간만 리포팅
python train.py --epochs 100 && teams-notify "학습 완료" || teams-notify "에러 발생"
```

- **상태 조회 봇 (Read-Only ChatOps)**: 코드를 넣는 대신 "지금 누가 몇 번 GPU 쓰고 있어?", "남은 VRAM 얼마야?"처럼 터미널 접속 없이 인프라 현황만 3초 만에 확인하는 쿼리형 봇이 실무 만족도가 훨씬 높다.

---

## 부록 D. 바이브 코딩 메신저 연동: 기존 사례와 사내 적용 전략

### D.1 바이브 코딩 방식이 만드는 시나리오

앞선 한계(부록 C)는 "개발자가 메신저 입력창에 코드를 직접 타이핑한다"는 전제 때문이었다. **사람은 자연어로 의도(Vibe)만 던지고, AI 에이전트가 코드를 짜서 GPU 위에서 실행·검증한 뒤 결과만 보고하는 형태**라면 실효성과 생산성이 폭발적으로 올라간다.

예시 — 팀원이 Teams에서: "@GX10-bot 이번 주에 나온 Qwen2.5-Coder-7B-Instruct 양자화 모델 서빙 띄우고, 우리 사내 Tizen 샘플 코드 넣어서 추론 속도(tokens/sec)랑 VRAM 얼마나 먹는지 벤치마크 뽑아줘."

AI 에이전트(백엔드)의 자율 수행 과정:

1. Hugging Face/Ollama에서 해당 모델 pull 또는 가중치 확인
2. GPU 할당 (VRAM 여유 확인 후 device=0)
3. 벤치마크용 테스트 코드 자동 생성 및 일회용 컨테이너에서 실행
4. 에러(OOM 등) 발생 시 스스로 배치 사이즈나 양자화 옵션(4bit/8bit)을 조정해 재시도 (Self-Correction)
5. 최종 지표(생성 속도, VRAM 점유 그래프, 샘플 출력)를 요약해 Teams Adaptive Card로 회신

이 방식이 매력적인 이유:

- **모바일/외근 중에도 GPU 리소스 활용**: 노트북을 펴서 터미널 열고 가상환경 잡을 필요 없이, 스마트폰에서 한 줄 툭 던져두고 커피 마시고 오면 벤치마크 결과가 도착해 있다.
- **귀찮은 보일러플레이트 자동화**: "간단한 임베딩 코사인 유사도 검증", "데이터셋 토큰 수 분포 히스토그램 그리기", "새 라이브러리 GPU 가속 여부 확인" 등 일회성 PoC 작업을 에이전트에게 외주.
- **비개발 직군/협업 팀의 장벽 제거**: 기획자나 PM이 엔지니어에게 부탁할 필요 없이, 메신저에서 직접 자연어로 프롬프트 테스트나 모델 성능 비교를 수행.

**현실적인 구현 아키텍처** — GX10 서버 내부에 Coding Agent Harness를 데몬으로 상주시키는 구조:

| 컴포넌트 | 추천 기술 스택 / 역할 |
|---|---|
| 메신저 인터페이스 | Teams Bot Framework / Webhook 엔드포인트 |
| 에이전트 브레인 | Claude Code, OpenClaw, 또는 LangGraph 기반 경량 에이전트 루프 |
| 실행 환경 (Sandbox) | Docker (GPU 패스스루 + 프로젝트 디렉토리 읽기 전용 마운트) |
| 도구 (Tools) | `run_bash_in_sandbox`, `read_file`, `check_gpu_status` |

**주의해야 할 가드레일 (현실적 제약)**:

- **GPU 독점 방지 (Quota)**: 에이전트가 무한 학습을 돌리거나 과도한 VRAM을 잡지 않도록, `timeout`(기본 5~10분)과 `max_memory` 제한을 명시적인 시스템 프롬프트로 강제.
- **비용 및 토큰 관리**: 코드를 짜고 에러를 고치는(ReAct 루프) 과정에서 LLM API 토큰이 소모되므로, 루프 최대 횟수(예: 최대 3회 재시도) 제한.
- **파일시스템 쓰기 격리**: 에이전트가 서버의 중요한 원본 데이터나 기존 프로젝트 소스코드를 덮어쓰지 않도록, 작업 디렉토리는 `/tmp/vibe_workspace/{job_id}` 형태로 완전히 격리.

### D.2 기존 메신저-에이전트 연동 사례

"메신저(Slack/Discord/Teams/Telegram)를 코딩 에이전트의 프론트엔드로 활용"하려는 시도는 오픈소스와 상용 SaaS 모두에서 활발하다. 접근 방식은 세 가지 흐름으로 나뉜다.

- **① 오픈소스 자율 에이전트의 메신저 브릿지**: OpenClaw, OpenDevin(All-Hands), AutoGen, CrewAI 등 — 기본적으로 Web UI/CLI 기반이지만 Slack/Discord/Telegram 연동 봇 어댑터를 공식/비공식 플러그인으로 제공. 채널에서 멘션으로 지시하면 백그라운드 샌드박스(Docker)에서 코드를 생성·수정·실행하고, 중간 과정(생각 과정, 터미널 로그 요약)과 최종 diff/결과를 메신저로 릴레이.
- **② 개발자 타겟 ChatOps / AI PR 에이전트**: Sweep AI, PR-Agent (Qodo), Devin(엔터프라이즈 연동) — 메신저나 GitHub Issue/Slack에서 자연어로 버그 제보/기능 요구사항을 받아, 에이전트가 브랜치를 따서 코드 수정 → 테스트 → GitHub PR 링크를 메신저에 회신. "채팅창 지시 → PR 생성 및 검증"의 전형적인 바이브 코딩 워크플로우.
- **③ 개인화/홈랩용 원격 코딩 봇 (Telegram/Discord 중심)**: 1인 개발자들이 VPS나 로컬 GPU 워크스테이션에 Claude Code, Cursor CLI, Aider 등을 데몬 형태로 띄워두고 Telegram Bot API를 물려 외출 중 스마트폰으로 지시하는 형태. "OO 라이브러리 GPU 가속 벤치마크 짜서 돌려봐", "어제 돌린 학습 로그 에러 잡아서 다시 실행해" 같은 일회성 작업을 모바일 메신저로 처리.

**이 접근들이 현업에서 겪는 공통 병목**:

- **인터랙션 피로도 (Chat Spoil)**: 에이전트가 "생각 중 → 파일 탐색 → 도구 호출 → 에러 수정"을 거칠 때 메신저 채널에 메시지가 수십 개씩 도배된다. 이를 막으려면 단일 카드를 계속 수정(Update)하는 세밀한 UI 핸들링이 필수적이다.
- **사람의 개입(Human-in-the-loop) 타이밍**: 에이전트가 위험한 명령(`rm -rf`, 대규모 패키지 설치, 포트 점유)을 감지했을 때 메신저 버튼(승인/반려)으로 승인을 받아내는 인터럽트 구조가 깔끔해야 한다.
- **로컬 파일시스템과의 컨텍스트 싱크**: 단순 일회성 스크립트 실행은 쉽지만, "기존 레포지토리 코드베이스를 읽고 고치는 작업"은 Git 브랜치 관리나 작업 디렉토리 격리가 제대로 안 되면 서버 환경이 금방 꼬인다.

**GX10 환경에 가장 잘 맞는 형태**: 전체 IDE를 대체하려 하기보다는 **"GPU 전용 일회성 태스크 러너"로 스코프를 좁히는 것**이 가장 성공 확률이 높다.

> Teams 멘션: "@GX10-bot 새 모델 X 임베딩 속도 벤치마크 코드 짜서 스펙 비교 리포트 카드 뽑아줘"
> 동작: 임시 작업 폴더(`/tmp/agent_runs/{id}`) 생성 → 에이전트가 Python 스크립트 작성 및 실행 → 터미널 아웃풋 파싱 → 성능/VRAM 메트릭과 함께 Teams Adaptive Card 회신 후 컨테이너 정리

이 정도 범위라면 복잡한 Git 충돌이나 사내 코드베이스 오염 걱정 없이, 팀원들이 외근 중이나 회의 중에도 GPU 파워를 자연어로 편하게 꺼내 쓸 수 있다.

---

## 부록 E. Cline 계열 세션 저장 구조와 사내 포크(cline-sr) CLI 점검

### E.1 Cline의 태생적 차이

Cline은 Claude Code처럼 공식적이고 완성도 높은 단독 Headless CLI 기능을 기본 제공하지 않는다. 태생이 VS Code 확장 프로그램(Extension)이기 때문이다 — 에이전트 루프와 파일 조작, 터미널 실행 로직이 VS Code의 내부 API(`vscode.window`, `vscode.workspace`, Webview)에 깊게 결합(Tight coupling)되어 있다. 반면 Claude Code는 애초에 순수 CLI 도구로 설계되어 `-p`, `--resume`, `--output-format json` 같은 파이프라인 연동 기능이 1급 시민으로 구현되어 있다.

Cline을 터미널/백그라운드에서 돌리려는 시도는 계속되고 있으나, 커뮤니티 CLI 포크/래퍼(Cline의 코어 에이전트 프롬프트와 툴 실행 루프만 분리한 오픈소스)는 메인스트림 확장만큼 업데이트가 빠르지 않고 안정성이 떨어진다.

### E.2 내부 세션(Task) 저장 구조

Cline 내부적으로도 모든 작업은 고유 Task ID 단위로 로컬 스토리지에 기록된다. 기술적으로는 이 JSON 파일을 읽어 이전 문맥을 이어갈 수 있지만, 외부 프로세스에서 깔끔하게 호출·제어할 수 있는 표준 CLI 플래그(인터페이스)가 열려 있지 않다.

**물리적 위치** (VS Code 환경, Linux 기준):

```
~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/tasks/{taskId}/
(VSCodium이나 원격 SSH 환경은 ~/.vscode-server/data/User/... 형태로 매핑)

tasks/
└── {taskId}/
    ├── api_conversation_history.json  # LLM API에 실제로 전달된 Raw 메시지 배열
    ├── ui_messages.json               # VS Code 웹뷰 UI 렌더링용 구조화 데이터
    └── checkpoints/                   # Git 기반 파일 스냅샷 (Checkpoints 기능 활성화 시)
```

**① `api_conversation_history.json` (LLM 컨텍스트 복원용)** — Anthropic Messages API 또는 OpenAI API 규격의 직렬화된 히스토리:

```json
[
  {
    "role": "user",
    "content": [
      { "type": "text", "text": "현재 디렉토리에서 GPU 벤치마크 스크립트 작성해줘" }
    ]
  },
  {
    "role": "assistant",
    "content": [
      { "type": "text", "text": "디렉토리 구조를 확인하겠습니다." },
      {
        "type": "tool_use",
        "id": "toolu_01...",
        "name": "list_files",
        "input": { "path": "." }
      }
    ]
  },
  {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_01...",
        "content": "benchmark.py\nrequirements.txt"
      }
    ]
  }
]
```

**② `ui_messages.json` (실행 상태 및 메트릭 파싱용)** — 도구 실행 결과, 터미널 로그 요약, 토큰 소비량, 비용(Cost) 정보가 분리되어 저장된다. 외부 메신저 봇으로 최종 실행 리포트를 긁어올 때 파싱하기 좋다:

```json
[
  {
    "ts": 1726000000000,
    "type": "say",
    "say": "task",
    "text": "현재 디렉토리에서 GPU 벤치마크 스크립트 작성해줘"
  },
  {
    "ts": 1726000005000,
    "type": "say",
    "say": "command_output",
    "text": "NVIDIA RTX... Driver Version: 550.x..."
  }
]
```

### E.3 외부 프로세스(메신저 봇)에서 활용하는 3가지 패턴

- **패턴 A: Read-Only 모니터링 및 상태 알림 (가장 구현 쉬움)** — 개발자가 VS Code에서 Cline에게 무거운 빌드/GPU 배치 태스크를 맡겨두고 자리를 비웠을 때. Python 파일 감시자(watchdog)가 `tasks/` 디렉토리를 모니터링 → 특정 Task의 `ui_messages.json` 갱신 감지 → 작업 완료(`completion_result`), 에러, 또는 사용자 승인 대기(`ask`) 상태가 기록되면 해당 텍스트를 파싱해 Teams/m-chat으로 푸시 알림.
- **패턴 B: 대화 히스토리 추출 후 독자 Agent 엔진으로 Replay** — 사용자가 메신저에서 `@bot resume {taskId} 아까 코드에서 배치 사이즈 64로 바꿔줘` 입력 → 백엔드가 해당 taskId의 `api_conversation_history.json`을 직접 로드 → 시스템 프롬프트 및 히스토리로 주입해 자체 LLM API 호출 또는 가벼운 CLI 에이전트 루프로 후속 작업 실행.
- **패턴 C: Headless Extension Runner (고급)** — VS Code를 실제로 띄우지 않고 가상 디스플레이(Xvfb)나 VS Code CLI의 `--extensionDevelopmentPath` 테스트 러너를 이용해 백그라운드에서 특정 Task ID를 주입한 상태로 확장 프로그램을 기동.

### E.4 사내 포크 cline-sr의 CLI 점검

사내 전용 포크인 cline-sr에 공식 CLI 도구가 이미 사내 패키지로 배포되고 있다면, "VS Code 종속성" 문제가 내부 엔지니어링으로 이미 해결된 상태다. 사내 개발팀이 직접 CLI를 패키징했다면 headless 파이프라인이나 CI/CD, 자동화 연동을 염두에 두고 만들었을 가능성이 매우 높다.

터미널에서 `cline-sr --help` (또는 `cline-sr task --help`)로 확인할 주요 포인트:

- 비대화형 실행(Non-interactive): `-p`, `--prompt`, `--message`, `-y` (도구 실행 자동 승인)
- 세션/태스크 ID 지정: `--task-id <id>`, `--resume <id>`, `--continue`
- 구조화된 출력: `--json`, `--output-format json` (메신저 카드 파싱용)
- 작업 디렉토리 지정: `--cwd`, `--dir`, `-C`

**세션 유지 구현 시나리오**:

- **Case A: CLI에 `--task-id` 또는 `--resume` 옵션이 있는 경우 (가장 이상적)** — 메신저 채널의 `thread_id`를 사내 DB/Redis에 `cline_task_id`와 1:1 매핑. 최초 메시지는 `cline-sr -p "..." --json`으로 실행해 반환된 `task_id`를 추출해 저장하고, 스레드 답글은 `cline-sr --resume <task_id> -p "..."`로 이어간다.
- **Case B: 단일 실행만 지원하고 재개 플래그가 없는 경우** — 사내 CLI가 생성하는 작업 경로(예: `~/.cline-sr/tasks/{id}/` 또는 `~/.config/...`)를 확인하고, 후속 요청 시 백엔드가 이전 task_id 폴더의 `api_conversation_history.json`을 읽어 컨텍스트를 주입하거나 해당 폴더를 작업 디렉토리로 지정해 실행.

**사내 환경 특성상 주의점**:

- **사내 프록시 및 인증 토큰**: CLI가 사내 사설 LLM 게이트웨이나 사내 포털 인증(SSO 토큰, 사내 CA 인증서)을 사용하는 경우, 웹훅을 수신하는 데몬 프로세스에도 동일한 환경변수(`HTTP_PROXY`, `NO_PROXY`, `REQUESTS_CA_BUNDLE`, 사내 API Key 등)가 전달되어야 한다.
- **사용자 권한 분리 (Sandbox)**: GX10 같은 공용 서버에서 데몬이 root나 단일 관리자 계정으로 cline-sr를 실행하면, 팀원의 자연어 명령에 의해 중요한 시스템 파일이나 다른 팀원의 작업물이 손상될 수 있다. 임시 디렉토리(`/tmp/cline_workspace/{thread_id}`)를 작업 디렉토리로 강제하는 것이 안전하다.

---

## 부록 F. 에이전트 CLI 비교와 이종 엔진 스왑

### F.1 OpenClaw / Hermes의 Headless 플래그

OpenClaw와 Hermes 모두 대화형 TUI 없이 단발성 명령을 실행하는 플래그를 지원하거나 동일하게 동작하는 인자를 가진다. 다만 도구마다 CLI 파서 설계 방식에 따라 플래그 이름과 세션 유지 방식에 차이가 있다.

**OpenClaw** — Claude Code와 유사한 CLI 에이전트 인터페이스를 지향하므로 옵션 체계가 거의 일치한다.

```bash
openclaw -p "현재 디렉토리에서 GPU 벤치마크 코드 작성해줘"   # Headless 실행 (-p / --prompt)
# 자동 승인: --yes 또는 -y (도구 실행 자동 컨펌)
# 세션 유지: --session <id> 또는 --continue 플래그
```

**Hermes** — 단일 실행과 세션 기반 에이전트 루프를 분리해 다루는 경향이 있다.

```bash
hermes-agent -p "bge-m3 모델 로드 스크립트 작성"   # 또는 hermes run "..."
# 자동 도구 승인: --non-interactive 또는 --auto-approve
# 세션 관리: SQLite/로컬 파일 기반 세션 스토리지, --session-id <id> 형태
```

앞서 작성한 파이썬 브릿지에 분기만 하나 추가하면 엔진을 자유롭게 스왑할 수 있다:

```python
# 예: EXEC_MODE를 "OPENCLAW"로 둘 경우
elif EXEC_MODE == "OPENCLAW":
    cmd = [
        "openclaw",
        "-p", prompt,
        "-y"
    ]
    if session_id:
        cmd.extend(["--session", session_id])
```

즉, 메신저 인터페이스와 세션 매핑 로직은 고정해 두고, 백엔드에서 호출하는 바이너리(claude, ollama launch claude, openclaw, hermes)만 갈아 끼우는 **플러그형 구조**로 대응할 수 있다.

### F.2 Hermes의 세션(resume) 제약과 우회 방법

Hermes는 Claude Code처럼 단일 플래그(`--resume <id>`) 하나로 CLI 헤드리스 세션을 완벽하게 재개하는 방식을 기본 제공하지 않거나, 버전에 따라 동작 제약이 크다.

- **인터랙티브 TUI 모드**: 터미널에서 띄울 때 이전 세션 목록을 띄워 선택하거나 재개하는 기능이 있다.
- **Headless 모드**: 단발성 실행 시 매번 독립된 작업 단위(Single-turn Task)로 간주하고 프로세스를 종료하는 것이 기본 라이프사이클이다. Claude Code처럼 `--output-format json`으로 고유 `session_id`를 명확히 뱉어내고 이를 다시 `--resume`으로 받아 넘기는 CLI 네이티브 헤드리스 세션 핸드셰이크가 표준화되어 있지 않다.

세션 맥락을 이어가야 할 때의 우회 방법:

- **① 작업 디렉토리 컨텍스트에 의존**: 일부 버전은 고유 ID 대신 특정 작업 디렉토리(CWD) 내 히스토리 캐시를 자동으로 이어받는 옵션을 제공한다.

```bash
# 특정 디렉토리 지정 및 이전 컨텍스트 이어받기
hermes run "배치 사이즈 64로 늘려서 다시 실행해줘" --continue --cwd ~/claude_workspace
```

- **② 파이썬 레벨에서 히스토리 누적 주입 (Wrapper 방식)**: CLI 자체의 resume 기능이 불안정하면, 브릿지 서버가 대화 히스토리를 텍스트로 보관했다가 프롬프트 앞단에 붙여 단발성 실행으로 넘긴다.

```python
# Hermes용 컨텍스트 주입 방식 예시
full_prompt = f"""
[이전 대화 맥락]
{accumulated_history}

[새로운 요청]
{user_text}
"""
cmd = ["hermes", "run", full_prompt, "--auto-approve"]
```

### F.3 CLI 헤드리스 세션 재개 편의성 비교

| 도구 | CLI 헤드리스 세션 재개 | 평가 |
|---|---|---|
| Claude Code | `--resume <session_id>` 지원 | 가장 완벽함. JSON 출력으로 ID 파싱 후 메신저 스레드 매핑이 가장 깔끔함 |
| OpenClaw | `--session <id>` 또는 `--continue` | Claude Code와 유사하여 메신저 연동 수월함 |
| Hermes Agent | 공식 CLI resume 플래그 미약 | 디렉토리 기반 캐시나 래퍼 차원의 프롬프트 누적이 필요함 |

스레드별 문맥 유지가 핵심인 대화형 봇을 구축할 때는 Hermes보다 Claude Code(또는 `ollama launch claude`)나 OpenClaw를 메인 엔진으로 쓰는 것이 구현과 안정성 면에서 유리하다. Cline 관련 정리는 부록 E 참고.

### F.4 Hermes의 내장 메신저 연동

Hermes는 외부 파이프라인에서 CLI를 억지로 래핑하지 않아도, 프레임워크 자체 수준에서 텔레그램이나 디스코드 같은 메신저 봇 통합 인터페이스를 내장하거나 어댑터 형태로 제공한다. "CLI 헤드리스 파이프라인(subprocess 래핑)"과 "자체 메신저 연동"은 구조적으로 접근법이 완전히 다르다.

- **상주형 봇 데몬**: 매번 파이썬에서 subprocess로 새로 띄우는 것이 아니라, Hermes 프로세스 자체가 텔레그램 봇 토큰을 물고 백그라운드 데몬으로 계속 떠 있다.
- **내장 세션 엔진**: 텔레그램의 `chat_id`/`user_id`를 Hermes의 내부 세션 DB가 직접 트래킹한다. CLI에서 `--resume` 플래그를 수동으로 넘길 필요 없이 대화방의 메시지 흐름이 자동으로 영속화된다.
- **설정 방식 (Config 기반)**: 환경변수나 config.yaml에 텔레그램 봇 토큰만 넣어두고 데몬을 기동하면 끝난다.

```yaml
telegram:
  token: "YOUR_TELEGRAM_BOT_TOKEN"
  allowed_users: [123456789]
model:
  base_url: "http://localhost:11434/v1" # 또는 Ollama Cloud
  model_name: "kimi-k-code"
```

| 비교 항목 | Claude Code / Ollama (`-p` 래퍼) | Hermes (내장 텔레그램 연동) |
|---|---|---|
| 동작 구조 | 외부 파이썬 스크립트가 CLI를 매 턴 호출 | Hermes 프로세스가 텔레그램 봇으로 상주 |
| 세션 유지 | `--resume <session_id>`를 명시적으로 전달 | 텔레그램 chat_id 기반으로 내부 자동 저장 |
| 도구 실행(Bash/Git) | Claude 고유의 정교한 파일 편집/터미널 도구 | Hermes의 Tool/Function Calling 엔진 사용 |
| 설정 복잡도 | 브릿지 코드(FastAPI/python-telegram-bot) 작성 필요 | 설정 파일(YAML)에 토큰 넣고 기동하면 끝 |
| 커스텀 제어 | 사내 메신저(m-chat/Teams) 등으로 전환 용이 | 제공되는 플랫폼(주로 텔레그램/디스코드)에 종속적 |

**실전 활용 팁**: 단독 챗봇으로 쓸 때는 파이썬 브릿지 코드를 짤 필요 없이 Hermes의 내장 텔레그램 모드를 켜서 데몬으로 띄우는 것이 세션 관리도 자동이고 가장 편하다. 반면 에이전트 협업(Multi-Agent)이나 사내 메신저 확장이 목적이면, 프로세스 간 입출력을 세밀하게 통제할 수 있는 CLI 기반(`-p` + 세션 관리 브릿지) 구조가 훨씬 유연하다.

---

## 부록 G. 텔레그램 멀티 에이전트 방 아키텍처

텔레그램 한 방(그룹 채팅)에 여러 개의 이종/동종 에이전트가 등장해 대화하는 것 — 기술적으로는 가능하지만, 텔레그램의 치명적인 제약 하나를 우회해야 한다.

> **텔레그램 봇 API 정책상, 봇은 다른 봇의 메시지를 읽을 수 없다** (Bots cannot see messages from other bots). 무한 루프나 스팸 방지를 위해 텔레그램 서버 레벨에서 막혀 있다.

### G.1 구현 가능한 3가지 아키텍처

**방식 A: "중계자(Orchestrator) 단일 봇" 구조 (가장 추천, 100% 안정적)**
텔레그램 방에는 단 하나의 공식 봇(`@AgentHubBot`)만 참여시킨다. 사용자가 메시지를 올리면 중계자 봇이 백엔드에서 Claude, Hermes, Ollama(Kimi-k-code) 등 여러 에이전트 프로세스에 동시에 또는 순차적으로 말을 전달하고, 발화자 이름을 앞에 붙여 출력한다.

```
[Claude-Architect]: "이 구조는 비동기 큐가 필요해 보입니다."
[Hermes-Coder]: "@Claude-Architect 의견 반영해서 Celery 기반 코드로 작성했습니다."
```

장점: 텔레그램 정책 제약을 전혀 받지 않으며, 에이전트 간 발언 순서(턴 제어), 무한 루프 방지, 토큰 소비 제어가 백엔드 파이썬 코드에서 완벽하게 통제된다.

**방식 B: Telegram MTProto (Userbot / 사용자 계정) 활용**
봇 API 대신 일반 전화번호 기반의 사용자 계정(Userbot)을 여러 개 만들어 에이전트로 띄우는 방식 (라이브러리: Telethon, Pyrogram). 에이전트들이 '봇'이 아니라 '일반 유저' 자격으로 방에 들어오므로 에이전트 A가 쓴 글을 에이전트 B가 실시간으로 읽고 반응할 수 있다. 단점: 전화번호가 여러 개 필요하고, 텔레그램 스팸 감지 시스템에 의해 계정이 일시 정지(Ban)될 리스크가 있다.

**방식 C: 백엔드 내부 이벤트 버스 + 각자 봇 전송 (하이브리드)**
방에 `@ClaudeBot`, `@HermesBot`, `@KimiBot` 등 여러 봇을 모두 초대해 둔다. 텔레그램 상에서는 봇끼리 메시지를 못 읽지만, 내부 백엔드(Redis Pub/Sub 또는 로컬 파이썬 메모리)에서 메시지를 공유한다. 유저가 말을 걸면 백엔드 버스에 등록되고, Claude가 답을 작성한 뒤 자기 토큰으로 텔레그램에 전송함과 동시에 내부 버스에도 브로드캐스트한다. Hermes는 텔레그램이 아닌 내부 버스에서 Claude의 메시지를 수신하고, 다음 턴 답변을 자기 토큰으로 텔레그램 방에 쏜다. 장점: 겉보기에는 진짜 여러 봇이 각자의 프로필 사진과 이름을 달고 대화하는 것처럼 보인다.

### G.2 필수적인 '제어 규칙'

에이전트들이 한 방에 모이면 단 몇 초 만에 API 한도와 토큰을 다 써버릴 수 있으므로 룰이 필요하다.

- **멘션 기반 호출 (Mention Trigger)**: 모든 메시지에 다 같이 대답하면 난장판이 된다. 유저나 상대 에이전트가 `@Claude`, `@Hermes`처럼 명시적으로 부를 때만 반응하게 한다.
- **최대 연속 턴 수 제한 (Max Turn Limit)**: 사람의 개입 없이 에이전트끼리 주고받는 핑퐁은 방당 최대 3~5턴으로 강제 종료.
- **사회자(Moderator) 역할 지정**: 한 에이전트(보통 추론 능력이 뛰어난 모델)에게 "사회자" 역할을 부여해, 다른 에이전트의 답변을 취합하고 사람에게 최종 결론을 보고한 뒤 대화를 끝내도록 프롬프트를 구성.

집에서 테스트할 때는 번호가 필요한 Userbot보다 방식 A(단일 중계 봇)로 가볍게 시작하거나, 각자 프로필을 살리고 싶다면 방식 C(백엔드 메시지 버스 공유)로 구현하는 것을 권장한다.

---

## 부록 H. 무인 운영 인프라: WOL · 자동 로그인 · 작업 스케줄러 · 전력 제어

폰으로 원격 에이전트를 쓰려면 컴퓨터를 켜고 다녀야 한다. 그런데 일 안 할 때와 부르기 전에는 컴퓨터가 전기를 잡아먹고 있게 하지 않으려면? GPU 워크스테이션/고사양 PC는 유휴(Idle) 상태에서도 60~100W 이상의 대기 전력을 소모하므로, **하드웨어 절전(Sleep/Wake)**과 **소프트웨어 전력 제어(Power Capping)** 두 축으로 해결할 수 있다.

### H.1 하드웨어 레벨: "원격으로 깨우고, 끝나면 재우기" (추천)

PC를 절전 모드(Suspend/Sleep, S3)로 두면 전력 소모가 1~3W 수준(스마트폰 충전기 수준)으로 떨어진다.

- **깨우기 (WoL + 텔레그램 연동)**:
  - 방법 A: 공유기(iptime, Asus 등)의 WOL(Wake on LAN) 기능 + 공유기 모바일 앱에서 터치 한 번으로 PC 부팅/웨이크업.
  - 방법 B (고급): 집에 상시 켜두는 초소형 저전력 기기(라즈베리 파이, 안드로이드 TV 셋톱박스, 항상 켜진 구형 안드로이드 폰)가 있다면, 텔레그램 봇을 거기에 띄워두고 폰으로 `/wakeup`을 쳤을 때 해당 기기가 PC로 매직 패킷(Magic Packet)을 쏘게 만든다.
- **다시 재우기 (Auto Suspend / Remote Sleep)**: 작업이 끝나면 폰에서 텔레그램 명령(`/sleep`)으로 PC를 즉시 절전 모드로 전환.
  - Linux: `systemctl suspend`
  - Windows: `rundll32.exe powrprof.dll,SetSuspendState 0,1,0`
  - 또는 30분 동안 GPU 사용률이나 터미널 활동이 없으면 스스로 절전 모드로 진입하도록 OS 전원 관리를 설정.
- **소프트웨어 레벨 전력 쥐어짜기 (PC를 켜두되 Always-On이어야 할 때)**:
  - GPU 유휴 전력 강제 제한: NVIDIA GPU는 기본 상태에서도 15~30W를 소모한다. 유휴 상태일 때 전력 한도(Power Limit)를 최저치로 낮춰두고, 에이전트가 실행될 때만 한도를 풀었다가 복귀시킨다: `sudo nvidia-smi -pl 100`
  - CPU 전원 관리 프로필(Power Governor): Linux라면 평소 `powersave`로 설정해 클럭을 최저(800MHz~1GHz)로 낮춰 CPU 패키지 전력을 10W 미만으로.

**가장 편한 실전 루틴**:

```
평소 (외출 중): PC는 절전 모드(Suspend, 전력 ~2W) 상태
→ 폰에서 공유기 앱(또는 저전력 중계기 텔레그램)으로 WOL 매직 패킷 전송
→ 부팅 완료 (약 5~10초): 시작 프로그램에 등록된 봇 자동 기동
→ 작업 수행: 폰 텔레그램으로 코드 작성 및 명령 지시
→ 사용 종료: 텔레그램에 /sleep 입력 → 봇이 스크립트를 실행해 PC를 다시 절전 모드로 진입
```

### H.2 작은 리눅스 머신에서 윈도우 PC 깨우기

같은 공유기(로컬 네트워크)에 유선으로 묶여 있으면 간단하다.

**① 윈도우 PC 사전 설정 (최초 1회)**

- **메인보드 BIOS/UEFI**: 부팅 시 Del/F2 → Power Management 또는 Advanced 메뉴 → `Wake on LAN`, `Power On By PCIE/PME`, `Network Boot` 항목을 Enabled로 변경
- **윈도우 네트워크 어댑터**: 장치 관리자 → 네트워크 어댑터 → 유선 랜카드 우클릭 속성
  - 전원 관리 탭: "이 장치를 사용하여 컴퓨터의 전원을 켤 수 있음" 체크, "매직 패킷 하나로만 컴퓨터의 전원을 켤 수 있음" 체크
  - 고급 탭: `Wake on Magic Packet` → Enabled. `Energy Efficient Ethernet`(절전형 이더넷) → 비활성화 권장
- **MAC 주소 확인**: 윈도우 터미널(CMD)에서 `ipconfig /all` → 유선 랜 어댑터의 물리적 주소 메모 (예: AA:BB:CC:DD:EE:FF)
- **주의**: 윈도우 '빠른 시작 켜기(Fast Startup)'가 켜져 있으면 완전 시스템 종료(Power Off) 상태에서 매직 패킷을 무시하는 경우가 있다. 제어판 전원 옵션 → 전원 단추 작동 설정에서 빠른 시작 켜기를 체크 해제하거나, 평소에 절전 모드(Sleep/Suspend)를 활용하는 것이 안정적이다.

**② 리눅스 머신에서 매직 패킷 쏘기**

```bash
# Ubuntu / Debian / Raspberry Pi OS 기준
sudo apt update && sudo apt install -y wakeonlan

# 실행 (MAC 주소는 윈도우에서 확인한 것으로)
wakeonlan AA:BB:CC:DD:EE:FF
# → "Sending magic packet to 255.255.255.255:9 with AA:BB:CC:DD:EE:FF"
```

**③ 파이썬으로 직접 쏘기 (외부 도구 설치 없이)**

```python
import socket

def wake_on_lan(mac_address: str):
    # MAC 주소 정규화 (콜론/하이픈 제거)
    cleaned_mac = mac_address.replace(":", "").replace("-", "")
    if len(cleaned_mac) != 12:
        raise ValueError("올바른 MAC 주소가 아닙니다.")

    # 매직 패킷 생성: 0xFF 6바이트 + MAC 주소 16회 반복 (총 102바이트)
    magic_payload = bytes.fromhex("FF" * 6 + cleaned_mac * 16)

    # UDP 브로드캐스트(포트 9)로 패킷 전송
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magic_payload, ("255.255.255.255", 9))
    print(f"WOL 패킷 전송 완료: {mac_address}")

# 사용 예시
wake_on_lan("AA:BB:CC:DD:EE:FF")
```

**④ 텔레그램 봇과 조합한 최종 시나리오**: 저전력 리눅스 머신(상시 가동, 전력 3~5W)에 가벼운 텔레그램 봇을 하나 올려두면 완결된다. 폰에서 `/pc_on` → 리눅스 머신이 WOL 패킷 발송 → 윈도우 PC 부팅(10~15초) → 리눅스 머신이 ping이나 SSH/서비스 포트 개방을 확인한 뒤 텔레그램으로 "윈도우 PC가 켜졌습니다" 회신.

### H.3 윈도우 무인 부팅: 자동 로그인 + 앱 자동 실행

어차피 윈도우가 켜져도 로그인도 해야 하고 에이전트 데스크톱 앱도 실행해야 한다. 사람이 키보드로 비밀번호를 치거나 마우스를 잡지 않아도, WOL 패킷을 받는 순간 실행까지 100% 무인으로 자동 완료되도록 만들 수 있다.

**① 윈도우 부팅 시 자동 로그인**

- **MS Sysinternals 'Autologon' 사용 (추천)**: MS 공식 사이트에서 Autologon 다운로드 → 실행 후 본인의 Windows 계정 ID와 비밀번호 입력 → Enable 클릭. 자격 증명이 LSA 암호화 영역에 안전하게 저장되며, 이후 전원이 켜지면 잠금 화면 없이 즉시 바탕화면 세션이 열린다.
- **보안 팁 (자동 로그인은 되되 화면은 잠그고 싶을 때)**: 시작프로그램에 `rundll32.exe user32.dll,LockWorkStation`을 등록하면, 백그라운드 세션과 앱은 모두 켜진 상태로 화면만 즉시 잠금(Lock) 상태로 전환된다.

**② 에이전트 데스크톱 앱 자동 실행**

- **방법 A: 시작프로그램 폴더** (가장 단순): `Win + R` → `shell:startup` 입력 후 엔터(시작프로그램 폴더 열림) → 앱 실행 파일(.exe)의 바로가기를 복사해 넣기.
- **방법 B: 작업 스케줄러(Task Scheduler)** (추천): 상세 절차는 아래 H.4.

### H.4 작업 스케줄러 상세 설정

UAC(관리자 권한 확인 창) 팝업 없이 부팅 및 자동 로그인 시 앱을 백그라운드에서 즉시 자동 실행하는 설정이다.

1. **작업 스케줄러 실행**: `Win + R` → `taskschd.msc` 입력 후 엔터
2. **새 작업 만들기 창 열기**: 오른쪽 작업(Actions) 패널에서 '기본 작업 만들기'가 아닌 **[작업 만들기(Create Task...)]** 클릭
3. **[일반] 탭 설정**
   - 이름: `AgentAutoStart` (식별하기 쉬운 이름)
   - 보안 옵션: 현재 로그인 계정이 선택되어 있는지 확인하고, **"가장 높은 수준의 권한으로 실행(Run with highest privileges)"에 반드시 체크** — 이 옵션이 켜져 있어야 실행 시 UAC 창에서 멈추는 현상이 방지된다.
4. **[트리거] 탭 설정**
   - [새로 만들기] → 상단 작업 시작(Begin the task) 드롭다운에서 **[로그온할 때(At log on)]** 선택
   - 설정 영역에서 [특정 사용자(Specific user)]가 본인 계정으로 지정되어 있는지 확인
   - (선택/권장) 고급 설정에서 **작업 지연 시간(Delay task for)**을 10초 또는 30초로 설정 — 네트워크 드라이버 및 백그라운드 서비스가 완전히 올라온 뒤 앱이 켜지도록 안정성 확보
   - [확인] 클릭
5. **[동작] 탭 설정**
   - [새로 만들기] → 동작(Action): **프로그램 시작(Start a program)** 선택
   - 프로그램/스크립트: [찾아보기]로 앱 실행 파일(.exe) 경로 지정
   - 시작 위치(Start in, 선택사항): 실행 파일이 있는 폴더 경로를 따옴표 없이 입력 (실행 파일이 참조하는 상대 경로 리소스나 config 파일을 정상 로드하기 위해 권장)
   - [확인] 클릭
6. **[조건] 및 [설정] 탭 검토**
   - [조건] 탭: "컴퓨터의 AC 전원이 켜져 있는 경우에만 작업 시작" 항목이 체크되어 있다면 해제하거나 확인 (데스크톱은 무관하나 전원 정책에 따른 차단 방지)
   - [설정] 탭: "요청 시 작업이 실행되도록 허용" 체크. "작업이 실패하는 경우 다시 시작 간격": 네트워크 문제 등으로 앱이 바로 켜지지 못할 때를 대비해 필요 시 1분 간격 재시도(최대 3회). "다음 시간 이상 작업이 실행되면 중지": 기본값(3일 등)이 켜져 있다면 체크 해제 — 데몬 형태로 계속 상주해야 하므로 강제 종료 방지
   - 최종 [확인]으로 저장
7. **동작 검증 (테스트 방법)**: 작업 스케줄러 라이브러리 목록에서 생성한 작업을 우클릭 → [실행(Run)] → 작업 관리자(`Ctrl + Shift + Esc`) 또는 화면에서 앱이 오류 없이 정상 실행되는지 확인

이렇게 설정해 두면 Autologon과 결합되어, 외부에서 WOL 신호로 PC를 켜는 즉시 사람 손을 타지 않고 앱이 알아서 구동된다. 모니터를 켜두지 않아도(가상 더미 플러그나 모니터 전원 꺼짐 상태에서도) 윈도우 내부 세션과 GPU는 완벽하게 활성화된다.

### H.5 앱 자체의 "시작 시 실행" 옵션 vs 작업 스케줄러

에이전트 데스크톱 앱 내부 설정(Settings/Preferences) 메뉴에 "Launch on system startup" 또는 "Start with Windows" 같은 옵션이 체크박스로 들어 있는 경우가 많다. 있다면 체크 하나로 끝낼 수 있어 가장 간편하다. 다만 원격 무인 부팅(WOL) 환경에서는 주의할 점이 있다.

앱 내부의 시작 옵션이 동작하는 원리는 윈도우 레지스트리(`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`)에 등록하는 방식이다.

| 비교 항목 | 앱 내 '시작 시 실행' 체크 | 작업 스케줄러 등록 |
|---|---|---|
| 설정 난이도 | 체크박스 한 번 클릭 (매우 쉬움) | 단계별 수동 입력 필요 |
| 관리자 권한 (UAC) | 권한이 필요할 경우 UAC 확인 창에서 멈춤 | "가장 높은 권한으로 실행"으로 UAC 자동 패스 |
| 네트워크 딜레이 | 부팅 즉시 켜져서 Wi-Fi/인터넷 연결 전 에러 날 위험 있음 | 10초~30초 지연 실행 설정 가능하여 안전 |
| 트레이 최소화 | 앱이 트레이 지원 시 백그라운드 상주 깔끔 | 창이 화면에 그대로 뜰 수 있음 |

**추천 검증 순서**:

1. 앱 내부 옵션 먼저 확인: 시작 옵션이 있다면 체크를 켜고 트레이 최소화(Start minimized)도 함께 켜둔다.
2. 테스트 재부팅: 재부팅했을 때 UAC 확인 창이나 권한 에러 없이 작업표시줄 트레이에 얌전히 올라오는지 확인한다.
3. 만약 UAC 창이 뜨면서 멈춘다면: 그때만 앱 내 옵션을 끄고 작업 스케줄러(가장 높은 권한으로 실행) 방식을 적용한다.

---

## 부록 I. 서브 에이전트 자율 분동과 CLAUDE.md 설정 예시

### I.1 Claude Code의 서브 에이전트 메커니즘

메인 에이전트가 복잡하거나 탐색량이 많은 작업을 만났을 때, 독립된 컨텍스트를 가진 서브 에이전트(Sub-agent)를 백그라운드로 스폰(Spawn)해 작업을 분할 처리하는 기능이 내장되어 있다 (내부적으로 Task Tool / Subagent Execution 형태).

```
[Main Claude Code Session]
       │
       ├── 필요 판단: "전체 레포지토리에서 인증 관련 로직 구조 파악 필요"
       │
       ├── Sub-agent A 생성 (격리된 컨텍스트)
       │    ├── grep, find, 수십 개 파일 읽기 수행
       │    └── 메인에게 "핵심 요약 리포트(3줄)"만 반환 후 종료
       │
       ├── Sub-agent B 생성 (격리된 컨텍스트)
       │    ├── 단위 테스트 스위트 전체 실행 및 에러 로그 수집
       │    └── 메인에게 "실패한 테스트 2개와 원인"만 반환 후 종료
       │
       └── 메인 에이전트: 요약된 결과만 보고 깔끔한 컨텍스트에서 최종 코드 수정
```

- **컨텍스트 격리**: 서브 에이전트가 수백 줄짜리 로그나 무거운 소스 코드를 뒤져도, 그 노이즈가 메인 에이전트의 대화 히스토리에 남지 않는다.
- **병렬 탐색**: 여러 모듈을 동시에 분석해야 할 때 각각 서브 에이전트를 띄워 결과를 취합한다.

### I.2 스스로 판단해서 서브 에이전트를 만들어 작업하게 하기

Claude Code는 작업의 복잡도와 컨텍스트 부하를 스스로 계산해 필요하다고 판단되면 사용자 명령 없이도 알아서 서브 에이전트를 스폰한다. 내부 에이전트 루프의 시스템 프롬프트와 툴 정의(Task/Agent 도구)에 위임 기준이 내장되어 있기 때문이다.

자율 스폰 기준:

1. **탐색 범위가 넓은 코드베이스 조사 (High-noise Search)**: 예) "이 프로젝트에서 인증 토큰 갱신 로직이 어디 구현되어 있는지 찾아서 버그 수정해줘" → 수십 개의 파일을 grep하고 열어보면 메인 세션 컨텍스트가 쓰레기 데이터로 가득 차므로, "탐색 전용 서브 에이전트"를 띄워 관련 파일 위치와 핵심 요약만 받아온다.
2. **시간이 오래 걸리거나 출력이 긴 명령어 실행 (Verbose Operations)**: 전체 빌드, 대규모 단위 테스트 스위트 실행, 수천 줄의 린트 검사 → 터미널 stdout이 수천 줄 쏟아지는 작업은 서브 에이전트에게 맡기고 "실패한 테스트 2개의 에러 스택트레이스"만 걸러서 전달받는다.
3. **병렬로 분리 가능한 독립 작업**: 프론트엔드 API 클라이언트 수정과 백엔드 라우트 핸들러 수정을 동시에 진행해야 할 때 각각 독립된 태스크로 발주한다.

명시적으로 유도할 수도 있다 (대화형 TUI뿐 아니라 Headless에서도):

```bash
claude -p "서브 에이전트를 활용해서, 먼저 backend/ 디렉토리의 DB 마이그레이션 구조를 조사하고 그 결과를 바탕으로 새로운 인덱스 생성 스크립트를 작성해줘" \
  --output-format json \
  --dangerously-skip-permissions
```

메인 에이전트는 내부적으로 Agent/Task 도구를 호출해 하위 태스크를 발주하고, 완료 보고를 받아 최종 응답(`result`)에 종합해 낸다.

**텔레그램/헤드리스 환경과의 시너지**:

- **메신저 메시지 길이 절약**: 서브 에이전트가 없으면 파일 10개 읽은 중간 로그가 메신저로 다 쏟아져 도배되지만, 서브 에이전트 구조를 타면 중간 탐색은 내부에서 조용히 끝내고 메신저에는 정제된 최종 결과만 전송된다.
- **토큰 및 비용 효율화**: 메인 대화 세션(`--resume <id>`)의 히스토리가 컴팩트하게 유지되어, 10턴 20턴 길게 이어가도 세션이 무거워져 느려지는 현상이 크게 줄어든다.

실행 흐름 예시 (텔레그램으로 "우리 프로젝트에서 메모리 누수 날 만한 곳 찾아서 고쳐줘"를 보냈을 때):

```
메인 세션: "작업 범위가 넓고 정적 분석이 필요하다"고 스스로 판단
→ 자율 분동 (Sub-agent 1): 전체 코드베이스 메모리 누수 패턴 검색
   → "db_pool.py의 커넥션 미반환, cache.py의 TTL 미지정 발견"
→ 자율 분동 (Sub-agent 2): 발견된 두 파일 대상 재현 테스트 코드 작성
→ 메인 세션: 결과를 종합해 최종 코드 패치 적용 및 커밋
→ 텔레그램 출력: "메모리 누수 2곳(db_pool, cache)을 찾아 수정 완료했습니다"
```

### I.3 자율 분동을 극대화하는 CLAUDE.md 예시

작업 디렉토리 루트에 CLAUDE.md 파일을 두고 프로젝트 룰을 선언해 두는 것이 가장 효과적이다. 헤드리스(`-p`) 실행 시 매 턴 시작 전에 이 파일을 가장 먼저 읽는다. 대규모 프로젝트에서 메인 컨텍스트 오염을 막고 탐색과 검증 작업을 서브 에이전트로 분동하도록 유도하는 설정 예시:

```markdown
# Project Guidelines & Agent Orchestration Rules

## 1. Context Preservation & Sub-agent Delegation
- **Context Hygiene**: 메인 세션의 컨텍스트 창은 최종 의사결정과 핵심 코드 수정에 집중해야 한다.
- **Mandatory Sub-agent Delegation**: 다음 조건 중 하나라도 만족하면 직접 처리하지 말고 반드시 하위 태스크(Sub-agent)를 스폰하여 위임할 것:
  1. **코드베이스 광역 탐색**: 3개 이상의 디렉토리를 탐색하거나 파일 구조를 모를 때 (`grep`, `find`, 정의 추적 등)
  2. **장문 출력 커맨드**: 전체 빌드, 대규모 단위 테스트 스위트, 장문의 정적 분석 린터(Linter) 실행
  3. **재현 테스트 작성**: 버그 패치 전 독립된 검증 스크립트 작성 및 실행
- **Reporting Protocol**: 서브 에이전트는 원시 출력(Raw Log)을 메인에 전달하지 말고, **핵심 요약(3~5줄)과 수정 대상 파일/라인 경로**만 간결하게 반환할 것.

## 2. Build & Test Commands
- **Fast Build**: `make -j$(nproc)` 또는 사내 빌드 명령
- **Unit Tests**: `pytest tests/unit -q` (메인 세션 실행 가능)
- **Full Test Suite**: `pytest tests/ -v` (출력이 길므로 반드시 서브 에이전트에 위임)
- **GPU Resource Check**: `nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv`

## 3. Code Standards & Architecture Patterns
- **Memory/VRAM Awareness**:
  - 모델 로드 및 텐서 연산 시 명시적인 디바이스 할당(`cuda:0`)과 예외 처리 블록 내 메모리 캐시 정리(`torch.cuda.empty_cache()`) 필수.
  - 배치 처리 작업은 OOM 방지를 위해 기본 청크 단위를 보수적으로 설정할 것.
- **Git Commit Rules**:
  - 서브 태스크 작업 단계에서는 커밋하지 않고, 메인 에이전트가 최종 검증을 마친 후 단일 단위 작업으로 커밋할 것.

## 4. Headless & Notification Mode Guardrails
- 비대화형(Headless) 환경이므로 사용자 입력 대기 상태에 머물지 말 것.
- 작업이 최종 완료되었을 때는 변경된 핵심 파일 목록과 테스트 통과 여부만 명확한 텍스트로 요약할 것.
```

**주요 세팅 포인트**:

- **구체적인 위임 조건 명시 (Trigger Conditions)**: 단순히 "서브 에이전트를 잘 써라"보다 3개 이상의 디렉토리 탐색, 전체 테스트 실행처럼 명확한 정량적 기준을 주어야 자율 분동 확률이 대폭 올라간다.
- **보고 형식 강제 (Reporting Protocol)**: 서브 에이전트가 가져온 수백 줄의 raw 로그가 메인으로 그대로 넘어오면 컨텍스트를 분리한 의미가 퇴색된다. 요약본과 파일 경로만 넘기도록 제한해 토큰을 절약한다.
- **리소스 및 안전장치**: VRAM 관리나 OOM 예외 처리 규칙을 명시해 두면, 에이전트가 코드를 작성하거나 벤치마크를 돌릴 때 메모리 누수 방지 로직을 사전에 반영한다.

이런 내용을 직접 작성할 필요 없이, Claude에게 한 줄로 지시하면 기존 파일 내용을 유지하면서 자연스럽게 병합해 준다:

```bash
claude "우리 프로젝트 루트의 CLAUDE.md에 컨텍스트 보호를 위해 광역 탐색이나 전체 테스트 실행 시 서브 에이전트를 적극 위임하도록 하는 가이드라인을 추가해줘"
```

Claude Code는 CLAUDE.md의 특수성을 이미 잘 알고 있어서, 프로젝트 구조와 어조에 맞춰 가장 깔끔한 마크다운 형식으로 알아서 작성하거나 업데이트해 준다.

---

## 맺음말: 구축 로드맵 제안

이 문서의 전체 흐름을 한 줄로 요약하면:

> `claude -p`(헤드리스 엔진) → 세션 관리(`--resume`) → 메신저 브릿지(텔레그램/Teams/m-chat) → 어댑터 패턴으로 엔진 추상화 → 안전 가드레일 → 확장 레이어(지식 주입/리소스 관리/후처리) → 멀티 에이전트/커스텀 TUI

우선순위 관점에서 권장하는 단계:

1. **안전 가드레일 (Command Interceptor)** — 원격/무인 실행 시 안심하고 백그라운드 위임이 가능해진다 (§8)
2. **리소스 모니터 & OOM 킬러** — GPU/VRAM 락다운과 PC 먹통 현상을 방지한다 (§9.3, 부록 B)
3. **로컬 지식 베이스 주입 (Markdown RAG)** — 내 코딩 스타일과 과거 노트를 기억하는 전용 비서가 된다 (§9.1)

> **구현 현황 (2026-09-06)**: §5·§6·§8의 내용을 실측 검증한 워크벤치가 `workbench/` 디렉토리에 완성되어 있다 — `parser.py`(NDJSON 정규화, 테스트 20건), `config_store.py`(엔진 선택 영속화), `server.py`(FastAPI + WebSocket, 1 턴 = `claude -p` 1 프로세스, `--resume` 세션 이어가기), `index.html`(대화 뷰/raw NDJSON 뷰/엔진 선택기). 실행: `python -m uvicorn server:app --port 8765` 후 브라우저에서 `http://127.0.0.1:8765`.

핵심 원칙은 하나다: **Claude CLI를 부품(Component)으로 보고 그 위에 나만의 관제 계층을 얹는다.** 엔진이 바뀌든(Claude → 오픈소스 모델), 인터페이스가 바뀌든(텔레그램 → 사내 메신저/TUI), 실행 환경이 바뀌든(클라우드 GPU → 로컬 워크스테이션), 가운데의 오케스트레이션 코어는 그대로 재사용할 수 있고, 그 설계가 곧 기술적 자산으로 남는다.

---

*문서 기준일: 2026-09-06. 원문은 Gemini 대화(2026-09-04 ~ 09-06)이며, 본 문서는 주제별 재편집본이다.*