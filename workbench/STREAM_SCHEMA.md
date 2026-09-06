# claude -p stream-json 스키마 — 실측 기준

> **본 문서의 원칙**: 공식 문서에는 완전한 이벤트 스키마 표가 없다([issue #24596](https://github.com/anthropics/claude-code/issues/24596)).
> 따라서 **리포의 실측 dump 가 문서보다 우선**한다.
> 근거: `dump_text.jsonl`(텍스트 턴), `dump_tool.jsonl`(툴/거부 턴), `dump_v263.jsonl`(CLI 2.1.263).
> CLI 버전: 2.1.263 (모델 glm-5.3-flash:cloud, Windows 11)

## 1. 실행 플래그 조합

```
claude -p "<텍스트>" --output-format stream-json --include-partial-messages --verbose
```

- `stream-json` 사용 시 `--verbose` **필수** (없으면 오류).
- stdout: NDJSON — **1줄 = 1 이벤트**. stderr는 별개(프로세스 오류 시 의미 있는 텍스트).
- 최종 이벤트는 항상 `result`.

## 2. 최상위 type 5종

| type | 역할 | 파서 처리 |
|---|---|---|
| `system` | 세션 메타·상태 이벤트 (subtype으로 분기) | `init`, `permission_denied`만 통과, 나머지 무시 |
| `stream_event` | Anthropic SSE 원본 래핑 (`--include-partial-messages` 때만) | `content_block_delta`의 text/thinking만 통과 |
| `assistant` | 모델 최종 메시지 (text/thinking/tool_use 블록) | `assistant_text`, `tool_use` |
| `user` | 툴 결과 반납 (tool_result 블록) | `tool_result` |
| `result` | 턴 최종 요약 | `result` |

공통 키: `type`, `session_id`(init부터 존재), `uuid`, `parent_tool_use_id`(서브에이전트 식별 — 메인은 null).

## 3. system (subtype별)

### 3.1 `init` — 턴 최초 이벤트

실측 키: `agents`, `apiKeySource`, `claude_code_version`, `cwd`, `fast_mode_state`,
`mcp_servers`, `memory_paths`, `model`, `output_style`, `permissionMode`, `plugins`,
`session_id`, `skills`, `slash_commands`, `subtype`, `tools`, `type`, `uuid`

- `tools`: 23개 툴 이름 배열 (기본 설정 기준).
- `permissionMode`: `default` | `bypassPermissions`(스킵 시).

### 3.2 `permission_denied` — **2.1.263 신규**

자동 거부가 구조화 이벤트로 옴 (2.1.109에는 없었고, 거부는 tool_result is_error로만 알 수 있었다).

```json
{"type": "system", "subtype": "permission_denied",
 "tool_name": "Write", "tool_use_id": "call_e7t7zr8m",
 "message": "you haven't granted it yet.", "session_id": "…"}
```

### 3.3 기타 subtype (실측 확인, 파서 무시)

| subtype | 내용 |
|---|---|
| `thinking_tokens` | `{estimated_tokens, estimated_tokens_delta}` |
| `hook_started` / `hook_response` | 훅 실행 (hook_started에 hook_path 등) |
| `status` | 상태 텍스트 |
| `api_retry` | API 재시도 (`attempt`, `max_retries`, `retry_delay_ms`, `error_status`) — 공식 문서 문서화됨, 실측 dump에는 미포함 |

## 4. stream_event — SSE 래퍼

래퍼: `{"type": "stream_event", "event": {SSE 원본}, "parent_tool_use_id": null, "session_id": "…", "uuid": "…"}`

`event.type`별 실측:

| event.type | 발생 | 파서 처리 |
|---|---|---|
| `message_start` | 메시지 시작 | 무시 |
| `content_block_start` | 블록 시작 | **무시** — tool_use는 이 시점 input이 비어있음(선행 신호). 완성본은 `assistant` 이벤트로 옴 → 카드 중복 방지(dedupe) |
| `content_block_delta` | 델타 | `delta.type`이 `text_delta`→`text_delta` 이벤트, `thinking_delta`→`thinking_delta` 이벤트, 그 외(`input_json_delta`, `signature_delta`) 무시 |
| `content_block_stop` | 블록 종료 | 무시 |
| `message_delta` | stop_reason 등 | 무시 |
| `message_stop` | 메시지 종료 | 무시 |

도구 호출 입력은 원래 SSE에서 `input_json_delta.partial_json`으로 스트리밍되지만,
우리는 `assistant` 이벤트의 완성된 `input` 객체만 사용한다.

## 5. assistant — 모델 메시지

`{"type": "assistant", "message": {"content": [블록들]}, "session_id": "…"}`

블록 = `{type: "text"|"thinking"|"tool_use"}`:
- `text`: `{type, text}` → `assistant_text` (턴당 최종 확정본 — 델타와 별개로 옴)
- `thinking`: 스트리밍에서 이미 노출됨 → 무시
- `tool_use`: `{type, id, name, input}` → `tool_use` (`input`은 완성 객체)

한 턴에 여러 assistant 이벤트가 올 수 있음 (텍스트→툴→텍스트).

## 6. user — 툴 결과

`{"type": "user", "message": {"content": [{type: "tool_result", …}]}}`

tool_result 블록: `tool_use_id`, `content`, `is_error`.
- `content`는 **문자열 또는 블록 배열** 두 형태가 관측됨 — 파서는 배열이면 text 블록들을 `\n` 조인.
- `is_error: true` = 거부/실패 (2.1.263에서는 병행 신호로 `system/permission_denied`도 옴).

## 7. result — 턴 최종 요약 (실측 필드)

| 필드 | 예/타입 | 비고 |
|---|---|---|
| `subtype` | `"success"` | 오류 시 `"error_during_execution"` 등 |
| `is_error` | `false` | |
| `duration_ms` / `duration_api_ms` | 4144 / 4052 | |
| `num_turns` | 2 | |
| `stop_reason` | `"end_turn"` | |
| `session_id` | UUID | 다음 턴 `--resume`에 사용 |
| `total_cost_usd` | 0.25381 | |
| `usage` | 토큰 상세 | 하단 표 |
| `modelUsage` | 모델별 집계 | `{inputTokens, outputTokens, cacheReadInputTokens, cacheCreationInputTokens, costUSD, contextWindow, maxOutputTokens}` |
| `permission_denials` | 배열 | `{tool_name, tool_use_id, tool_input}` — 거부 상세가 result에도 요약됨 |
| `terminal_reason` | `"completed"` | |
| `fast_mode_state` | `"off"` | |
| `uuid` | UUID | |

`usage` 하위 키(실측): `input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
`cache_read_input_tokens`, `server_tool_use`, `service_tier`, `cache_creation`,
`inference_geo`, `iterations`, `speed`

> **캐시 참고**: glm 프록시 게이트웨이 + ollama 호환 레이어 모두 `cache_read/cache_creation = 0`
> (캐시 인프라 부재 — 모드 B). 비용 선형 증가 원인. 자세한 것은 가이드 문서 §7.

## 8. 파서 정규화 대응표 (parser.py)

| 원본 | → 정규화 이벤트 |
|---|---|
| `system/init` | `init` |
| `system/permission_denied` | `permission_denied` |
| `stream_event/content_block_delta(text_delta)` | `text_delta` |
| `stream_event/content_block_delta(thinking_delta)` | `thinking_delta` |
| `assistant`(text 블록) | `assistant_text` |
| `assistant`(tool_use 블록) | `tool_use` |
| `user`(tool_result) | `tool_result` |
| `result` | `result` |
| JSON 파싱 실패 줄 | `raw` |
| 그 외 전부 | `None` (무시) |

## 9. 참고 자료

- 공식 headless 가이드: https://code.claude.com/docs/en/headless
- CLI 레퍼런스: https://code.claude.com/docs/en/cli-reference
- SDK 스트리밍 출력(StreamEvent 상세): https://code.claude.com/docs/en/agent-sdk/streaming-output
- 문서 요청 이슈: https://github.com/anthropics/claude-code/issues/24596
- 서드파티 리버스엔지니어링 표(claude-code-rs): https://github.com/takelushi/claude-code-rs/blob/main/docs/claude-cli.md