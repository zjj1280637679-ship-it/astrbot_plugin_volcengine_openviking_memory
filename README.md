# astrbot_plugin_volcengine_openviking_memory

为 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 接入 **火山方舟 Agent Plan 的「Agent 记忆」（OpenViking Context 托管服务）**，提供跨会话长期记忆。

自动捕获群聊/私聊对话写入 OpenViking 记忆库，每次 LLM 请求前按当前消息**语义召回**相关记忆并注入上下文；也可由模型主动调用 `ov_memory_search` / `ov_memory_remember` 工具。记忆空间**按用户或群隔离**，召回方式、隔离粒度、提交阈值全部可在 AstrBot WebUI 配置页调整。

## 前置条件

- AstrBot >= 4.23.1
- 已订阅**火山方舟 Agent Plan 个人版**，并在「使用配置 → 配置 Harness」开启 **Agent 记忆** 抵扣开关（仅支持北京地域、需实名认证）
- 已在 OpenViking Context 控制台创建数据库，并拿到 **OpenViking API Key**
  - 位置：OpenViking Context 控制台 → **用户管理** 页面
  - ⚠️ 不是方舟 `ark-` 开头的模型 Key；ark Key 无法访问 OpenViking 服务（会返回 401）

## 安装

1. 在 AstrBot WebUI → 插件管理 → 安装：`https://github.com/zjj1280637679-ship-it/astrbot_plugin_volcengine_openviking_memory.git`
2. 在插件配置页填写 **ov_api_key**（其余有默认值）
3. 重载插件，发送 `/记忆 状态` 验证服务连通

## 工作方式

```
用户消息 ──► on_user_message ──► OpenViking 会话（按 用户/群 隔离的 agent_id）
模型回复 ──► on_llm_response ─► 追加 assistant 消息
    │
    ├─ 达到 消息数/token 阈值 或 空闲超时 ──► commit 会话 ──► 服务端提取长期记忆
    │
LLM 请求前 ──► on_llm_request ──► 按当前消息 search/find ──► 召回块注入上下文
模型主动 ──► ov_memory_search / ov_memory_remember 工具
```

### 记忆隔离

默认开启 `scope_isolation`：每个用户/群使用独立的 `X-OpenViking-Agent`，记忆互不串：

- 群聊：`astrbot:<平台>:group:<群号>`
- 私聊：`astrbot:<平台>:user:<用户id>`

关闭后所有对话共享一个记忆空间。前缀用 `agent_id_prefix` 配置，用于区分不同机器人。

## 配置项

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `ov_base_url` | `https://api.vikingdb.cn-beijing.volces.com/openviking` | 托管服务地址，一般不改 |
| `ov_api_key` | （空） | OpenViking API Key，必填 |
| `agent_id_prefix` | `astrbot` | X-OpenViking-Agent 命名空间前缀 |
| `scope_isolation` | `true` | 按用户/群隔离记忆空间 |
| `capture_enabled` | `true` | 自动捕获对话写入记忆 |
| `capture_bot_replies` | `true` | 同时捕获机器人回复 |
| `capture_access` | `free` | 对话捕获权限（三值） |
| `recall_access` | `free` | 自动召回注入权限（三值） |
| `tool_access` | `free` | LLM 工具权限（三值） |
| `delete_access` | `admin` | 删除记忆权限（三值，默认仅管理员） |
| `tool_io_access` | `free` | 工具调用记录权限（三值） |
| `command_access` | `free` | 管理命令权限（三值） |
| `recall_mode` | `auto` | 召回方式：`auto` 自动注入 / `tool` 仅工具 / `both` 双模式 / `off` 关闭 |
| `recall_api` | `find` | 召回接口：`find`（列表，兼容最好）/ `context`（服务端组装，不支持时自动回退） |
| `recall_limit` | `8` | 最多召回条数（1-30） |
| `recall_min_score` | `0.35` | 召回最低相关分（0-1） |
| `recall_token_budget` | `2000` | 注入上下文 token 预算（200-8000） |
| `recall_target_uri` | （空） | 可选召回范围限定，如 `viking://user/xxx/memories` |
| `commit_message_threshold` | `20` | 累积 N 条消息后提交 |
| `commit_token_threshold` | `4096` | 累积 token 超阈值后提交 |
| `commit_idle_seconds` | `1800` | 空闲 N 秒后提交积压 |
| `capture_tool_io` | `false` | 是否把模型工具调用写入记忆 |
| `request_timeout_seconds` | `60` | API 请求超时 |
| `debug_log` | `false` | 详细日志 |

## 权限控制（三值开关）

捕获、自动召回、模型工具、删除记忆、工具调用记录、管理命令六个功能各自有独立的三值开关：

| 取值 | 含义 |
|------|------|
| `free` | 所有用户/对话可用（默认） |
| `admin` | 仅管理员对话可用；普通用户触发时返回"仅管理员可用" |
| `off` | 禁用；**模型工具直接不注册**，模型看不到对应工具 |

管理员判定：优先平台上报的角色（`event.is_admin()`，群主/群管理），兜底比对 AstrBot 配置的 `admins_id` 列表。

典型用法：
- `capture_access=admin` + `recall_access=admin`：记忆只服务机器人管理员，普通群友的闲聊不会污染记忆库
- `tool_access=off`：完全不给模型提供记忆搜索/写入工具（仅保留自动注入）
- `delete_access=off`：彻底关闭删除能力（工具隐藏 + 命令禁用）
- `delete_access=admin`（默认）：删除记忆仅管理员可用；`/记忆 清空` 始终要求管理员并二次确认
- `command_access=admin`：`/记忆` 命令只有管理员能操作

## 知识库模式（后台输入知识，AI 检索召回）

开启 `knowledge_base_mode` 后，插件行为从「记忆模式」切换为「知识库模式」：

| 行为 | 记忆模式（默认）| 知识库模式 |
|------|------|------|
| 对话自动捕获 | ✅ 从对话学习 | ❌ 关闭（不从闲聊学习）|
| 知识输入 | 模型工具可写 | **仅管理员**经 `/知识 添加` 写入 `viking://resources/kb/` |
| 模型工具 | search / remember / delete | **仅 search**（只读，remember/delete 隐藏）|
| 自动召回 | 搜索记忆 | 搜索知识库（默认收窄到 `knowledge_root`）|
| 删除/清空 | `/记忆 删除/清空` | `/知识 删除`（仅管理员）|

### 知识库命令（文本）

| 命令 | 说明 |
|------|------|
| `/知识 添加 <内容>` | 添加一条文本知识（仅管理员；写入后需等待约 20-30 秒向量索引完成才可被检索）|
| `/知识 列表` | 列出知识库全部条目 |
| `/知识 查看 <uri>` | 查看某条知识的原文 |
| `/知识 删除 <uri>` | 删除一条知识（仅管理员）|
| `/知识 状态` | 知识库状态（条目数、召回范围）|

配置项：
- `knowledge_base_mode`（bool）：是否开启知识库模式
- `knowledge_root`（string，默认 `viking://resources/kb`）：知识存放的资源目录；知识库模式下召回默认收窄到该目录

> 说明：当前仅支持纯文本知识（markdown 语法可用）。URL/文档导入待后续扩展。
> 托管服务删除偶发 503 锁错误，插件已内置重试；若仍失败可在 OpenViking 控制台手动删除。

## 指令与工具

| 触发 | 说明 |
|------|------|
| `/记忆 状态` | 查看服务连通、隔离粒度、权限配置、待提交量与上次提交时间 |
| `/记忆 搜索 <词>` | 手动语义搜索记忆 |
| `/记忆 删除 <uri>` | 按 viking:// URI 删除单条记忆（受 `delete_access` 控制）|
| `/记忆 清空 [确认]` | 清空全部记忆（管理员 + 二次确认）|
| `/记忆 提交` | 手动触发当前会话提交与记忆提取 |
| `ov_memory_search(query, limit)` | LLM 工具：语义检索长期记忆（只读） |
| `ov_memory_remember(content)` | LLM 工具：把重要事实显式写入并立即提交（有副作用） |
| `ov_memory_delete(uris)` | LLM 工具：按 URI 列表删除记忆（有副作用，受 `delete_access` 控制）|

## 开发

```bash
python -m unittest discover -s tests -v
```

单元测试使用进程内 mock 服务器，不依赖真实服务与 AstrBot 本体。

## 说明

- 自动注入的记忆块通过 `req.extra_user_content_parts` 以临时内容（`.mark_as_temp()`）注入，不写入会话历史、不破坏提示词缓存；旧版 AstrBot 自动回退到 `system_prompt` 追加。
- 记忆提取由服务端 commit 触发生成，初次使用需要积累几轮对话后再提交，检索效果才会显现。
