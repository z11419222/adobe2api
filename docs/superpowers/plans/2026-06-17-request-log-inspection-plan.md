# Request Log Inspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 请求日志支持保存清洗后的完整请求体，并在管理后台通过媒体预览弹窗查看，同时支持按起始时间、模型筛选和快速跳页。

**Architecture:** 后端继续以 `data/request_logs.jsonl` 作为日志持久化来源，扩展日志记录字段、查询参数和详情读取接口；默认日志列表仍保持当前最新在顶部的行为。前端在请求日志页新增独立筛选条和跳页控件，媒体预览弹窗按需拉取日志详情展示清洗后的完整请求体，避免列表接口携带大字段。

**Tech Stack:** FastAPI, Python 3.10, file-backed JSONL store, vanilla HTML/CSS/JavaScript admin UI.

---

## 1. 需求边界

### 必做

- 保存每条外部 OpenAI 风格请求的完整请求体，但必须先清洗 base64 图片内容。
- 管理后台点击日志里的媒体“查看”按钮后，仍能看图片或视频，并能在同一个弹窗中查看该日志的完整请求体。
- 日志筛选支持直接输入 `2026-06-17 17:51:46` 这种时间格式。
- 填写起始时间后，只显示该时间点之后的请求日志，且最老的匹配请求显示在顶部。
- 支持按模型筛选请求日志。
- 现有分页保留，并增加快速跳转到指定页数的能力。

### 不做

- 不保存原始 base64 图片正文。
- 不改变生成接口、Adobe 上游调用逻辑或模型解析逻辑。
- 不把请求体展示放到日志表格单元格里，避免表格变重、变乱。
- 不改动 Token 管理、刷新配置导入、错误详情弹窗之外的无关管理后台功能。
- 不迁移已有日志文件；旧日志没有完整请求体时，详情弹窗显示“该日志未保存请求体”。

## 2. 现状定位

- `app.py` 负责请求日志中间件，当前只提取 `model` 和 `prompt_preview`，提示词预览会清洗换行并截断到 180 字符。
- `core/stores.py` 中的 `RequestLogRecord` 是日志记录结构，当前没有请求体字段。
- `core/stores.py` 中的 `RequestLogStore.list` 当前从文件尾部取窗口并倒序返回，所以默认最新日志在顶部。
- `api/routes/admin.py` 的 `/api/v1/logs` 当前只支持 `limit` 和 `page`，没有筛选参数或详情接口。
- `static/admin.html` 的日志区域只有统计范围、刷新、清空、表格和上一页/下一页。
- `static/admin.js` 的 `loadLogs` 当前只请求 `/api/v1/logs/running`、`/api/v1/logs` 和 `/api/v1/logs/stats`。
- `static/admin.js` 的 `openPreview` 当前只接收媒体 URL 和媒体类型，弹窗没有日志详情上下文。
- `static/admin.css` 当前已有预览弹窗和分页样式，可在此基础上扩展。

## 3. 数据设计

### 日志记录新增字段

- 在 `RequestLogRecord` 增加可选字段 `request_body`。
- `request_body` 保存清洗后的完整请求体，优先保存为 JSON 对象或数组；如果请求体不是 JSON，则保存为清洗后的字符串。
- 列表接口默认不返回 `request_body`，只返回轻量字段和一个布尔字段 `has_request_body`。
- 详情接口返回单条日志完整记录，包含 `request_body`。

### base64 清洗规则

- 递归扫描请求体里的对象、数组和字符串。
- 对 `data:image/...;base64,...`、`data:video/...;base64,...`、`data:application/octet-stream;base64,...` 这类 data URL，保留 MIME 类型和估算大小，替换正文。
- 对疑似纯 base64 的长字符串，超过安全阈值后替换为占位描述，保留字符长度和估算字节数。
- 对普通 prompt 文本、模型 ID、HTTP 图片 URL、非 base64 字段原样保留。
- 清洗后的占位文本需要让用户知道内容被省略，例如“base64 image omitted, mime=image/png, approx=1.8MB”。
- 清洗失败时不能影响主请求；日志字段降级为“request body unavailable after sanitization”，同时保留正常请求处理流程。

### 隐私与体积控制

- 不保存请求头，所以不会额外保存 `Authorization`、Cookie 或服务 API Key。
- 保留 URL 图片地址，因为它是用户请求体的一部分；如果后续需要隐藏外部 URL，应另起需求。
- 日志仍受现有 `max_items=5000` 保留策略约束。
- 由于 base64 已被清洗，单条日志体积主要来自文本 prompt 和结构化参数。

## 4. 后端接口方案

### `/api/v1/logs` 列表接口

新增查询参数：

- `start_time`：文本格式，支持 `YYYY-MM-DD HH:MM:SS`，秒可选时可接受 `YYYY-MM-DD HH:MM`。
- `start_ts`：Unix 秒级时间戳，供前端或脚本直接传入；与 `start_time` 同时存在时优先使用 `start_ts`。
- `model`：模型 ID 精确匹配，空字符串表示全部模型。
- `order`：`desc` 或 `asc`。默认 `desc`；如果提供了 `start_time` 或 `start_ts` 且没有显式传 `order`，默认改为 `asc`。
- `page` 和 `limit`：沿用现有分页参数。

返回结构保持兼容：

- `logs`：当前页日志。
- `page`、`limit`、`total`、`total_pages`：基于筛选后的结果计算。
- `order`：实际使用的排序。
- `filters`：回显实际筛选条件，便于前端显示状态。

### `/api/v1/logs/{log_id}` 详情接口

新增单条日志详情接口：

- 需要管理员登录。
- 从 `data/request_logs.jsonl` 中查找指定 `id` 的最新记录。
- 返回完整日志记录，包含 `request_body`。
- 找不到时返回 404。
- 旧日志没有 `request_body` 时，返回记录本身并带 `has_request_body=false`。

### 时间解析规则

- `start_time` 以服务端本地时区解析；当前运行环境按本地时间展示日志，因此筛选输入也按本地时间理解。
- 接受用户要求的空格格式 `2026-06-17 17:51:46`。
- 可兼容浏览器控件常见的 `2026-06-17T17:51:46`，但 UI 主输入仍使用空格格式。
- 格式非法时返回 400，错误信息明确提示可用格式。

## 5. 后端实现任务

### Task 1: 请求体清洗器

**Files:**

- Modify: `app.py`

- [ ] 增加一个小型清洗函数，输入原始请求体字节，输出可 JSON 序列化的清洗后请求体。
- [ ] 清洗函数内部负责 JSON 解析、递归遍历和 base64 字符串替换。
- [ ] 清洗函数对异常保持封闭，不向请求主流程抛出异常。
- [ ] 保持现有 `_extract_logging_fields` 职责不变：它继续只负责模型和提示词预览。

### Task 2: 写入完整请求体字段

**Files:**

- Modify: `app.py`
- Modify: `core/stores.py`

- [ ] 在 `RequestLogRecord` 增加 `request_body` 可选字段。
- [ ] 在请求日志中间件读取 raw body 后，生成清洗后的 `request_body`。
- [ ] 在 live log 初始记录中不写入完整请求体，避免运行中列表过重。
- [ ] 在最终日志写入 `RequestLogRecord` 时写入清洗后的 `request_body`。
- [ ] 在按 token 重试产生 attempt 日志的路径中同步写入同一份清洗后的 `request_body`。

### Task 3: 日志列表筛选与排序

**Files:**

- Modify: `core/stores.py`
- Modify: `api/routes/admin.py`

- [ ] 扩展 `RequestLogStore.list`，支持 `start_ts`、`model`、`order` 参数。
- [ ] 无筛选且 `order=desc` 时保留当前尾部窗口读取逻辑，避免默认列表性能倒退。
- [ ] 有筛选或 `order=asc` 时扫描现有 JSONL 文件，过滤后再分页。
- [ ] `model` 使用精确匹配，避免短关键字误伤多个模型。
- [ ] 列表返回前移除 `request_body`，补充 `has_request_body`。
- [ ] `/api/v1/logs` 解析 `start_time` 和 `start_ts`，计算实际排序规则并回显筛选条件。

### Task 4: 日志详情读取

**Files:**

- Modify: `core/stores.py`
- Modify: `api/routes/admin.py`

- [ ] 在 `RequestLogStore` 增加按 `id` 获取最新记录的方法。
- [ ] 新增 `/api/v1/logs/{log_id}` 管理接口。
- [ ] 确保 `/api/v1/logs/errors/{code}` 仍优先匹配错误详情路径。
- [ ] 详情接口返回 `has_request_body`，并在旧日志缺失请求体时保持兼容。

### Task 5: 日志筛选 UI

**Files:**

- Modify: `static/admin.html`
- Modify: `static/admin.css`
- Modify: `static/admin.js`

- [ ] 在统计卡片和日志表格之间增加筛选条。
- [ ] 起始时间使用文本输入框，不使用 `datetime-local` 作为唯一入口，因为用户需要直接输入 `2026-06-17 17:51:46`。
- [ ] 输入框 placeholder 使用 `2026-06-17 17:51:46`。
- [ ] 增加快捷按钮：`最近1小时`、`今天0点`、`最近24小时`。
- [ ] 增加模型输入框，默认空值表示全部模型。
- [ ] 增加 `查询` 和 `重置` 按钮。
- [ ] 筛选生效时显示结果提示，例如“已筛选：2026-06-17 17:51:46 之后 · 模型 firefly-... · 按时间正序”。
- [ ] 重置后清空筛选条件，页码回到 1，并恢复默认最新在顶部。

### Task 6: 快速跳页 UI

**Files:**

- Modify: `static/admin.html`
- Modify: `static/admin.css`
- Modify: `static/admin.js`

- [ ] 在现有上一页/下一页之间或旁边增加页码输入框。
- [ ] 输入框限制为正整数，显示范围提示使用当前 `total_pages`。
- [ ] 增加 `跳转` 按钮。
- [ ] 在页码输入框按 Enter 时触发跳转。
- [ ] 输入小于 1 时跳到第 1 页；输入大于最大页时跳到最后一页。
- [ ] 跳页时保留当前筛选条件和排序条件。

### Task 7: 预览弹窗显示请求体

**Files:**

- Modify: `static/admin.html`
- Modify: `static/admin.css`
- Modify: `static/admin.js`

- [ ] 日志行的“查看”按钮携带 `log_id`，不把请求体塞进 DOM 属性。
- [ ] 打开媒体预览时同时按 `log_id` 请求详情接口。
- [ ] 预览弹窗中增加“媒体预览”和“请求体”两个区域或切换标签。
- [ ] 请求体区域展示格式化后的 JSON；旧日志缺失时显示“该日志未保存请求体”。
- [ ] 增加“复制请求体”按钮，复制清洗后的请求体文本。
- [ ] 详情接口加载失败时不影响媒体预览，只在请求体区域显示错误。

### Task 8: 统计与运行中日志行为

**Files:**

- Modify: `static/admin.js`
- Modify: `api/routes/admin.py` only if implementation chooses to extend stats filters

- [ ] 统计卡片继续表示统计范围选择器的总览，不强制跟随表格筛选。
- [ ] 表格筛选结果数量由 `/api/v1/logs` 的 `total` 和分页信息体现。
- [ ] 运行中日志继续显示在表格顶部，但只在默认未筛选状态显示。
- [ ] 当起始时间或模型筛选生效时，不混入运行中日志，避免筛选结果和排序语义不一致。

## 6. UI 细节

### 筛选条布局

- 第一行：起始时间输入、模型输入、查询、重置。
- 第二行：快捷时间按钮和当前筛选提示。
- 在窄屏下纵向堆叠，输入框宽度占满。
- 筛选提示使用弱强调样式，不抢统计卡片视觉层级。

### 跳页布局

- 保留现有 `上一页`、`第 X / Y 页`、`下一页`。
- 在同一行追加 `跳至 [页码] 页` 和 `跳转`。
- 页码输入宽度控制在 72px 左右，避免分页条变得拥挤。

### 请求体展示

- 请求体区域使用等宽字体和暗色背景。
- 长内容在弹窗内滚动，不撑开弹窗高度。
- JSON 格式化缩进为 2 个空格。
- base64 占位文本需要醒目但不使用错误色，避免误导用户以为请求失败。

## 7. 验证方案

### 静态验证

- 运行 `py -3.10 -m compileall -q app.py api core`，确认 Python 语法无误。
- 检查浏览器控制台，确认管理后台无 JavaScript 运行错误。

### 后端行为验证

- 构造包含长 prompt 的请求，确认日志详情保留完整 prompt，不再只有 180 字符预览。
- 构造包含 data URL base64 图片的请求，确认日志详情只保存占位信息，不保存 base64 正文。
- 调用 `/api/v1/logs` 不带筛选条件，确认默认仍是最新日志在顶部。
- 调用 `/api/v1/logs` 带 `start_time=2026-06-17 17:51:46`，确认只返回该时间之后的日志且按正序排列。
- 调用 `/api/v1/logs` 带 `model`，确认只返回精确匹配模型的日志。
- 调用 `/api/v1/logs` 同时带 `start_time` 和 `model`，确认两个条件叠加生效。
- 调用 `/api/v1/logs/{log_id}`，确认返回完整清洗后的 `request_body`。

### 管理后台手动 QA

- 登录管理后台，进入请求日志页。
- 不输入筛选条件，确认默认列表、上一页、下一页行为保持不变。
- 输入 `2026-06-17 17:51:46` 查询，确认最老匹配日志在顶部。
- 输入模型 ID 查询，确认筛选提示和结果一致。
- 使用快捷时间按钮，确认会自动填充起始时间并刷新列表。
- 在跳页输入框输入有效页码并点击跳转，确认跳到目标页。
- 输入超过最大页的页码，确认跳到最后一页。
- 点击带媒体的日志“查看”，确认媒体正常展示。
- 在同一弹窗查看请求体，确认 JSON 可读且 base64 已清洗。
- 点击复制请求体，确认剪贴板内容为清洗后的请求体。

## 8. 风险与处理

- 日志文件扫描性能：当前最多保留 5000 条，筛选时全量扫描可接受；默认无筛选路径保留尾部窗口读取以降低常用场景成本。
- 旧日志兼容：旧记录没有 `request_body`，详情弹窗显示缺失提示，不需要迁移。
- 路由冲突：新增 `/api/v1/logs/{log_id}` 时必须保留 `/api/v1/logs/errors/{code}` 的具体路径优先匹配。
- 大文本 prompt：完整请求体可能仍然较长，弹窗需要内部滚动，列表接口不返回请求体。
- 时间理解偏差：UI 明确标注“本地时间”，后端按服务端本地时区解析空格格式时间。

## 9. 实施顺序建议

1. 先实现请求体清洗和日志写入，确认 JSONL 新字段正确。
2. 再实现后端筛选、排序、详情接口，保证 API 可独立验证。
3. 再接入日志筛选 UI 和跳页 UI。
4. 最后改造预览弹窗展示请求体。
5. 做完整手动 QA，确认默认行为没有回归。

## 10. 自检结果

- 需求覆盖：完整请求体保存、base64 清洗、弹窗查看请求体、时间输入格式、时间正序筛选、模型筛选、快速跳页均已有对应任务。
- 兼容性：默认日志列表排序和分页保留；旧日志缺失请求体有降级展示。
- 范围控制：方案只涉及请求日志后端、管理后台日志 UI 和样式，不触碰生成业务逻辑。
- 无代码示例：本文档只描述修改方案、文件职责、行为和验证步骤，不包含实现代码片段。
