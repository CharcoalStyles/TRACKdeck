# v2 handoff: stock LFM scoring

Everything needed to score `liquid/lfm2.5-1.2b` (stock, no LoRA) against the v2 day-organiser.
All files except this one are generated from the live code by `generate.py`; `search_web.mcp.json`
is the one captured input (see below).

## Files

| File | What it is |
|---|---|
| `system_prompt.txt` | `SYSTEM_PROMPT`, the base prompt every turn gets |
| `addendum_one_shot.txt` | appended when `one_shot=True` (device and voice turns) |
| `addendum_day_planning.txt` | appended when `mode == "day_planning"` |
| `tools.json` | the 19 tool schemas, OpenAI function format, in registration order (18 local, `search_web` last) |
| `mode_tools.json` | per-mode tool restriction (`day_planning` sees 4 tools, every other turn sees all 19) |
| `search_web.mcp.json` | `search_web` as captured from the live MCP server (`searxng-mcp-server`), with its output schema |
| `settings.defaults.json` | `GET /settings` body on a fresh install |
| `settings.schema.json` | JSON schema of that body |

## Prompt assembly

Per turn, in `agent/graph.py` `call_llm`:

```
SYSTEM_PROMPT
+ ONE_SHOT_ADDENDUM            if one_shot
+ DAY_PLANNING_ADDENDUM        if mode == "day_planning"
+ "\n\nCURRENT DATE AND TIME: " + <local time>      always, e.g. "6:41 PM on Thursday 15 October 2026"
```

The datetime format is `%-I:%M %p on %A %-d %B %Y` in `settings.timezone`. Recalled context is gone in
v2, so nothing else is injected. Chat history is trimmed to `max_history_tokens`.

The exact string a given turn used is recoverable: each interaction event carries `prompt_version`, and
`<EVENT_LOG_DIR>/prompt_versions/<version>.json` holds that prompt, both addenda, the mode tool names and the
tool schemas as bound at the time. Note the `search_web` entry in those files can be a stub when the MCP
server was not running; the schema in `tools.json` here is the real one.

## Tools

19 = 18 local + `search_web`. The MCP server also offers `search_images`, `search_videos`, `search_news` and
`fetch_url`; `agent/tools/all_tools.py` filters those out (`MCP_TOOL_ALLOWLIST`), so the model never sees them.
Before this commit they were bound, which made a live run 23 tools. Any earlier eval log from a run with the MCP
server up has the extra four.

`jot_note` takes no arguments by design: the app saves the user's exact words, so the model only has to choose
it. A one-shot or voice turn where the model calls no tool at all is saved as a capture anyway (`fallback`), and
the reply is the fixed string "Saved to today's captures."

Write guards that run outside the model and change what a score should be measured against: a start in the
past is refused with a corrective error; `date_guard` fixes the date when the user said exactly one of
tonight/today/tomorrow; successful calendar and reminder writes get a templated reply
(`reply_by: "template"`); a reply that claims a change with no matching tool call is replaced.

## Reply routing (`reply_by` in the log)

`template` (built in code from a tool result), `lfm` (the tool model's own text, including when the writer failed),
`gemma` (the writer model, only if `lmstudio_writer_model` is set), `fallback` (the canned capture reply).
`agent/writer.py` `decide()` picks the writer reason: `empty_draft`, `tool_error`, `prose_tool`, `mode:day_planning`,
`one_shot`, `conversation`, `short_draft`, `long_draft`. With no writer model set everything is `lfm`, `template`
or `fallback`.

## Settings shape

`settings.defaults.json`. Stored in `settings.db` (key/value), edited by `POST /settings`. Times are local
`HH:MM`. Notes for scoring:

- `mcp_servers` is `"{}"` in the defaults here only because `SEARXNG_URL` was unset when it was generated; with
  it set the first-run seed is `{"searxng": {"transport": "stdio", "command": "uvx", "args": ["--with", "fastmcp<4", "searxng-mcp-server"], ...}}`.
- `gotify_token` is write-only; the response reports `gotify_token_set`.
- `lmstudio_chat_model` (tool model) comes from `LMSTUDIO_CHAT_MODEL` at first run and is not part of
  `GET /settings`; it is recorded per turn in `models.tool`. `lmstudio_writer_model` blank means no writer.
- `timezone` and `default_location` feed the datetime line and the weather tools.

## Log schema

`<EVENT_LOG_DIR>/events-YYYY-MM.jsonl` (default `data/logs`), append-only, one JSON object per line, UTF-8.
Every line has `ts` (local ISO time to the second, in `settings.timezone`) and `kind`. A logging failure never
breaks the action being logged. A turn's artifacts and its capture/edit events join on the interaction's ULID.

`source` is the channel: `voice`, `text`, `device`, `dashboard` or `job`.

### `interaction` (one per agent turn)

| Field | Notes |
|---|---|
| `interaction_id` | 26-char ULID, sortable by time |
| `source`, `thread_id`, `one_shot` (bool), `mode` (`null` or `"day_planning"`), `timezone` | |
| `user_text` | after keyword-prefix stripping |
| `tools` | list of steps `{name, args, result, error}` in call order; `result` truncated at 4000 chars with a `…[truncated]` suffix |
| `reply`, `reply_by` | final text and who wrote it (`template`, `lfm`, `gemma`, `fallback`) |
| `fallback_capture` | true when no tool was called on a one-shot/voice turn and the words were saved as a capture |
| `models` | `{tool, writer}`; writer is `null` when off |
| `prompt_version` | `<git sha10>+<sha256[:12]>` or just the digest; keys into `prompt_versions/` |
| `artifacts` | what the turn created or changed, see below |

### `artifact` (also embedded in `interaction.artifacts`, minus `kind`/`ts`)

`{type, id, op, ...}` plus `origin_interaction_id` (the turn's id, or `null` for dashboard-made ones).

| `type` | `op` | extra fields |
|---|---|---|
| `calendar_event` | `create`, `update`, `delete` | `title`, `start`, `end` (UTC ISO, absent on delete); dashboard creates also carry `source: "dashboard"` |
| `reminder` | `create`, `cancel` | `message`, and `due` (local ISO) on create |
| `capture` | `create` | `text`; embedded in the interaction only, the standalone record is the `capture` event |

### `capture`

`capture_id`, `source`, `via` (`tool` the model chose `jot_note`, `fallback`, or `form` the dashboard), `text`
(whitespace-flattened), `origin_interaction_id`.

### `edit` (dashboard changes after the fact; the corrections to score against)

`artifact_type` (`capture` or `calendar_event`), `action` (`update` or `delete`), `fields` (names changed),
`before`, `after` (`null` on delete), `source: "dashboard"`, `origin_interaction_id` (the turn that made the
artifact, `null` if it was made by hand). Calendar edits carry `id`; capture edits carry `capture_id` and `date`
(`YYYY-MM-DD`). Capture fields are `text` and `done`; event fields are `title`, `start`, `end`, `location`,
`description`.

### `convert` (capture turned into something else)

`artifact_type: "capture"`, `capture_id`, `date`, `to` (`reminder`, `event` or `task`), `when` (the time the user
gave, or `null`), `minutes` (task length, or `null`), `source: "dashboard"`, `origin_interaction_id`. A
conversion that creates a reminder or event also writes its own `artifact` event with no origin (it is made
outside a turn).

### Reading it for scoring

A turn is good if nothing was edited afterwards: join `edit`/`convert` events to `interaction` by
`origin_interaction_id`. A `convert` on a `fallback` capture means the model should have called a tool; an
`edit` of an event's `start` means the date or time was wrong.

## Regenerating

See the header of `generate.py`. Refresh `search_web.mcp.json` only if the MCP server changes; to capture it,
list the tools of `uvx --with "fastmcp<4" searxng-mcp-server` over stdio (needs `SEARXNG_URL` set to any URL).
