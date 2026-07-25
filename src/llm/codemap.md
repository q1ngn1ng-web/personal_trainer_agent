# src/llm/

## 职责

`src/llm/` 是项目内**统一的 LLM 调用层**，对 DeepSeek（或兼容 Chat Completions 协议的端点）做"单入口 + 强结构化输出"的封装：

- **唯一调用入口**：`client.complete()`，项目内所有 LLM 调用必须经过此处（`client.py` 文件级 docstring 已明示 `All DeepSeek calls MUST go through complete`）。
- **Prompt / Schema 解耦**：通过 `prompts.PROMPT_REGISTRY` 与 `schema.SCHEMA_REGISTRY` 两个字典，按 `prompt_name`（如 `topic_validation`、`baseline_q`、`md_generation` 等）查表获得模板与 JSON Schema。
- **结构化保证**：模型输出经 `validators.parse_and_validate` 做 JSON 抽取 + `jsonschema` (Draft202012) 校验，部分 purpose 还需通过语义校验（如 `baseline_q` 的关键词覆盖）。
- **弹性**：调用失败经 `retry.retry_with_feedback` 做指数退避重试，并把上次错误作为 `__feedback__` 反馈回写到下次 prompt；耗尽后查询 `fallback.fallback_for` 静态降级载荷。
- **可观测**：返回字典统一携带 `output_text / output_json / latency_ms / tokens_in / tokens_out / retry_count / model / prompt_name / prompt_version`，方便上层写入 SQLite 与日志。

## 设计

### 1. 模块拆分
| 文件 | 角色 |
|---|---|
| `client.py` | 统一入口 + HTTP 调用 + 组装 system/user message + 编排校验与降级；定义 `LLMError` / `LLMValidationError` 异常。 |
| `prompts.py` | 7 套 prompt 模板常量 + 版本常量 + `PROMPT_REGISTRY: dict[str, tuple[template, version]]`。 |
| `schema.py` | 7 个 JSON Schema 常量 + `SCHEMA_REGISTRY: dict[str, dict]`。 |
| `validators.py` | `parse_and_validate`（JSON 抽取 + jsonschema）、`keyword_coverage_check`（语义校验）。 |
| `retry.py` | 基于 `tenacity.Retrying` 的指数退避重试器，把异常消息注入下一次变量。 |
| `fallback.py` | 静态降级载荷字典 `FALLBACK_BASELINE_Q` 与查询函数 `fallback_for(purpose)`。 |
| `__init__.py` | 留空，模块无对外包级 API（消费方按子模块精确导入）。 |

### 2. 配置与常量（来自 `client.py`）
- 环境变量：`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com`）/ `DEEPSEEK_MODEL`（默认 `deepseek-v4-flash`），通过 `python-dotenv` 加载。
- 常量：`DEFAULT_TEMPERATURE=0.2`、`DEFAULT_MAX_TOKENS=4096`、`REQUEST_TIMEOUT_S=60`。
- 关键字覆盖校验白名单：`KEYWORD_COVERAGE_PURPOSES = {"baseline_q"}`，仅对该 purpose 触发 `_semantic_check`。

### 3. 客户端/提示词/Schema/校验/重试/降级 链路

```
上游 service
   │  complete(prompt_name, variables, schema=?, max_attempts=3)
   ▼
client.complete ── 校验 prompt_name 是否在 PROMPT_REGISTRY
   │  若外部未传 schema，则把对应 SCHEMA_REGISTRY[prompt_name] dump 进 variables["schema"]
   ▼
retry.retry_with_feedback(call_with_count, prompt_name, variables, max_attempts)
   │  tenacity.Retrying(stop_after_attempt(3), wait_exponential(1,1,10), reraise=True)
   │  每次失败把异常文本写入 working["__feedback__"]
   ▼
client._run_once(prompt_name, variables)
   │  1) 取 (template, version) from PROMPT_REGISTRY[prompt_name]
   │  2) client._render_prompt: template.format(**variables) + 可选 "[上一次尝试错误反馈] ..."
   │  3) 拼 messages:
   │        system: "你是一名严格的 JSON 生成助手…"
   │        user  : 渲染后的 prompt（含 schema dump 与 __feedback__）
   │  4) client._call_api → POST {DEEPSEEK_BASE_URL}/chat/completions
   │        成功 → (content, prompt_tokens, completion_tokens) + 记录 latency_ms
   │        失败 → 抛 LLMError（401/4xx/5xx、非 JSON、空 choices、requests.RequestException）
   │  5) 若有 schema：
   │        validators.parse_and_validate(text, schema)
   │           ├─ _extract_json: 优先匹配 ```json``` 围栏；否则取首个 "{" 与最后一个 "}" 之间的内容
   │           ├─ json.loads → jsonschema Draft202012Validator.validate
   │           └─ 顶层必须为 dict，否则抛 ValidationError
   │        client._semantic_check(prompt_name, output_json, variables)
   │           └─ 若 purpose == "baseline_q"：
   │                _coerce_keywords(variables["keywords"]) → keyword_coverage_check
   │                任一 question 文本不含任一 keyword（大小写不敏感）→ LLMValidationError
   │  6) 返回可观测字典 {output_text, output_json, latency_ms, tokens_in, tokens_out,
   │                     retry_count=0, model, prompt_name, prompt_version}
   ▼
retry 循环 → 成功时把 retry_count = (调用次数 - 1) 写回结果
   │  重试条件：_call_api 抛 LLMError；parse_and_validate 抛 json.JSONDecodeError / ValidationError；
   │           _semantic_check 抛 LLMValidationError；任一上述异常都被 tenacity 捕获并 retry。
   │  重试机制：wait_exponential(1,1,10) —— 至少 1s、至多 10s 间隔，最多 3 次。
   ▼
耗尽仍异常：
   │  ├─ fallback.fallback_for(prompt_name) 返回非 None（当前仅 baseline_q 有静态降级）
   │  │    → 返回同样结构的字典，output_text = json.dumps(fb, ensure_ascii=False)，
   │  │      retry_count = 实际尝试次数（包含失败轮），latency/tokens = 0
   │  └─ 未定义降级 → 重新抛出原异常（上层 service 自行处理）
```

### 4. 降级载荷详情（`fallback.py`）
- `FALLBACK_BASELINE_Q`：硬编码的 3 道诊断题（dimension 分别为 concept/concept/write，difficulty 1/2/3），附中文 `reference_answer`。
- `fallback_for("baseline_q")` → 返回该载荷并 `logger.warning("serving preset baseline_q fallback (LLM exhausted)")`。
- 其他 purpose → 返回 `None`，调用方走异常传播路径；`logger.warning("no fallback defined for purpose=...")`。

### 5. 校验细节（`validators.py`）
- `parse_and_validate(text, schema)`：
  - `_extract_json`：先剥 ` ```json ` 围栏；无围栏则用首末花括号切片；空文本抛 `ValueError("empty LLM output")`。
  - `json.loads`：失败抛 `json.JSONDecodeError`，并 `logger.warning`。
  - 顶层非 dict：抛 `jsonschema.ValidationError("top-level JSON is not an object: ...")`。
  - 用 `Draft202012Validator(schema).validate(parsed)` 校验；失败抛 `ValidationError`。
- `keyword_coverage_check(questions, keywords)`：
  - 任一参数为空 → `False`。
  - keywords 统一小写、去空白。
  - 每题 `q["question"].lower()` 必须命中至少一个 needle，否则 `False`；非 dict 题也判 `False`。

### 6. 重试细节（`retry.py`）
- `tenacity.Retrying(stop=stop_after_attempt(max_attempts), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)`。
- 闭包内复制 `working = dict(variables)`；每次失败 `working["__feedback__"] = str(exc)`，于是下一次 `_run_once` 渲染时 `_render_prompt` 会追加 `[上一次尝试错误反馈] ...` 段。
- `reraise=True` + 外层 `except Exception:` 仅做 error 日志，最终把最后一次异常抛给 `client.complete`。
- 任何被 `call_fn` 抛出的异常都触发重试（包括 schema 校验、语义校验、HTTP 错误）。

## 数据流

```
┌────────────────────────────────┐
│ 上游 service（trainer/keyword/ │
│ calibration/topic_validation/  │
│ scoring/baseline）             │
└────────────────┬───────────────┘
                 │ 完整 variables dict
                 │ (含 topic/description/keywords/answers/...)
                 ▼
        client.complete(prompt_name, variables, schema?, max_attempts=3)
                 │
                 │ ① 校验 prompt_name 存在
                 │ ② 把 schema dump 写入 variables["schema"]（若未传）
                 │ ③ attempt_count 计数归零
                 ▼
        retry_with_feedback → tenacity 循环
                 │
                 │ ┌── 失败 ──→ 写 working["__feedback__"] = str(exc) → 退避后重试
                 ▼ ▼
        _run_once(prompt_name, working)
                 │
                 │ (a) 取模板与版本
                 │ (b) _render_prompt 渲染（追加 __feedback__ 段）
                 │ (c) 组装 messages (system: 严格 JSON / user: 渲染 prompt)
                 │ (d) _call_api ──HTTP POST─→ DeepSeek /chat/completions
                 │     返回 (content, prompt_tokens, completion_tokens)
                 │ (e) 若有 schema:
                 │       parse_and_validate → _extract_json + json.loads + jsonschema
                 │       _semantic_check（仅 baseline_q → keyword_coverage_check）
                 │ (f) 构造观测 dict
                 ▼
        ┌─────────────────────────┐
        │ 成功 → 返回观测 dict     │
        │ 失败耗尽:                 │
        │   fallback_for 非 None → │
        │     返回静态降级 dict     │
        │   fallback_for is None →│
        │     重抛异常给上游       │
        └─────────────────────────┘
                 │
                 ▼
       上游 service 拿到 output_json（已是 dict）
       写入 SQLite（data/trainer.db），并附带 tokens/latency/retry_count
```

观测字段约定（与所有上层 service 共享）：
```
{
  "output_text":   str,          # 原始模型文本（含 fallback 时为 json.dumps(fb)）
  "output_json":   dict | None,  # 解析并校验后的对象；无 schema 或 fallback 时可为 None/dict
  "latency_ms":    int,
  "tokens_in":     int,
  "tokens_out":    int,
  "retry_count":   int,          # 实际额外重试次数（成功 = max(0, attempts-1)；fallback = 实际 attempts）
  "model":         str,          # DEEPSEEK_MODEL
  "prompt_name":   str,
  "prompt_version": str,         # 来自 PROMPT_REGISTRY，便于回溯
}
```

## 集成点

### 上游消费者（`src/services/`）
全部通过 `from src.llm.client import complete` 引用，间接消费 prompt/schema/registry：

| Service | 调用入口 | 主要 prompt_name | 备注 |
|---|---|---|---|
| `services/topic_validation.py` | `complete` | `topic_validation` | 同时读 `PROMPT_REGISTRY` / `SCHEMA_REGISTRY`。 |
| `services/keyword_service.py` | `complete` | `keyword_generation` | 同上。 |
| `services/baseline_service.py` | `complete` | `baseline_q` | 还显式 `from src.llm.fallback import fallback_for` 与 `from src.llm.validators import keyword_coverage_check`；是唯一用到 fallback 与关键词覆盖校验的业务方。 |
| `services/scoring_service.py` | `complete` | `baseline_scoring` | 同 topic_validation 模式。 |
| `services/calibration_service.py` | `complete` | `weekly_calibration` | 还 `from src.llm.client import LLMError` 捕获异常；引用 `WEEKLY_CALIBRATION_PROMPT_VERSION`。 |
| `services/trainer_service.py` | `complete` | `md_generation` / `pretrain_checklist` | 训练文件包生成入口。 |

### 第三方依赖（requirements.txt）
- `requests`：HTTP 调用（`_call_api`）。
- `python-dotenv`：`.env` 加载（`load_dotenv()`）。
- `tenacity`：指数退避重试器（`retry.py`）。
- `jsonschema`：Draft202012 校验（`validators.py`）。

### 环境契约
- 必须在 `.env` 提供 `DEEPSEEK_API_KEY`（缺则 `LLMError("DEEPSEEK_API_KEY is not set")`）。
- 可覆盖 `DEEPSEEK_BASE_URL`（用于 OpenAI 兼容代理）与 `DEEPSEEK_MODEL`。

### 异常传播
- `LLMError`：HTTP/网络/解析失败（基类）。
- `LLMValidationError`：`LLMError` 子类，schema 校验失败或 `_semantic_check` 失败。
- 重试耗尽后：有降级则吞掉异常并返回降级 dict；无降级则把最后一次异常（`LLMError` / `LLMValidationError`）原样抛给上层 service，由 `calibration_service` 等自行处理。