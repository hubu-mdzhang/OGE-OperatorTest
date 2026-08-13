# OGE 算子批量自动化测试系统 V2

本项目面向 OpenEarth/OGE 开发中心 `http://www.openearth.org.cn/develop`，以 Playwright 替代人工复制代码、点击运行、等待、查看 Console/Globe、截图和登记结果的机械流程。

V2 的正式调度源只有 `input/operators.csv`。`算子代码与结果.docx` 不再作为全量业务输入，也未打包到本版本中。

## 当前业务总表基线

源文件：`input/source/副本算子排序表0806返修.xlsx`

- 总记录数：204
- 可执行记录：189（编号 1～189）
- 缺英文名且缺代码：15（编号 190～204）
- 这 15 条固定记为 `SKIPPED_NO_CODE`，不伪造执行
- 原表存在一组重复英文名：`Feature Model Regress`（编号 173、182）；系统告警但按 `case_id` 分开测试
- 189 份非空代码已通过 Python 语法检查

以后在原 Excel 补齐 190～204 的英文名和代码后，只需重新运行 `build_input.bat`，Runner 无需修改。

## 快速开始

仓库不包含业务总表 Excel、登录态和运行产物。请先自备：

1. 将业务总表放入 `input/source/`（默认文件名见下文「Excel → CSV」），或运行时用 `build_input.bat <你的Excel路径>` 传入；
2. `aaaa.har` 为脱敏后的真实契约样例，其中用户标识已替换为占位符 `<OGE_USER_ID>`；如需替换为新的真实 HAR，请先按同样方式脱敏。

在 Windows CMD 中依次运行：

```bat
setup.bat
build_input.bat
login.bat
self_test.bat
run.bat --start-id 1 --end-id 1
```

单算子 Smoke Test 通过后，再扩大范围：

```bat
run.bat --start-id 1 --end-id 10
run.bat
```

登录失效并安全停止后：

```bat
login.bat
resume.bat
```

`login.bat` 只打开专用 Edge Profile，等待人工登录并验证 Monaco、Console、运行按钮和 Globe；项目不保存用户名或密码。

## Excel → CSV

`build_input.bat` 调用 `tools/build_input.py`，默认读取：

```text
input/source/副本算子排序表0806返修.xlsx
```

输出：

```text
input/operators.csv
input/operators.build_report.json
```

CSV 的核心字段包括：

- `case_id`
- `category`
- `name_cn`
- `operator_name`
- `code`
- `expected_result_type`
- `enabled`
- `source_status`
- `source_original_status`
- `source_development_status`
- `source_manual_test_status`
- `validation_mode`
- `expected_console_regex`

构建器自动检查总数、可执行数、缺代码数、缺英文名数、重复编号、重复英文名和代码语法。重复编号或非空代码语法错误会阻止 CSV 覆盖；重复英文名只告警，因为 `case_id` 才是主键。

## 单算子状态机

每条记录依次执行：

1. 检查 `enabled`、英文算子名、代码和筛选范围。
2. 检查持久化登录态和完整页面契约。
3. 重载工作区，保存运行前 Globe。
4. 通过 Monaco Model API 写入完整代码；真实页面未暴露 `window.monaco` 时回退到 textarea 键盘输入。
5. 注入校验：Model API 路径逐字符回读比对；键盘路径校验编辑器尾部渲染区等于代码后缀、头部渲染区等于代码前缀（短代码两端渲染区覆盖全文，等效全量校验），长代码由运行后 `executeCode` 载荷逐字符比对兜底。
6. 记录运行前 Console 条数，只读取本次新增日志。
7. 点击带 `/svgs/run.svg` 且包含“运行”的真实按钮。
8. 同时监听 `executeCode`、目标 DAG 对应的 `executeDag`、HTTP 状态和耗时。
9. 等待 Console 成功、明确错误或超时，并继续等待目标 DAG 全部返回。
10. 无论结果如何，都保存强制证据并立即追加 JSONL/CSV。

Network 不是简单计数。系统先从本次 `executeCode` 响应提取目标 DAG ID，再按 ID 与 `executeDag` 逐一绑定。目标为 3 个、结果为 2 个 success + 1 个 failed 时，直接判为执行失败；后台无关 DAG 不计入本算子。

## 三层判定

每条记录同时保留：

| 层级 | 典型值 | 含义 |
| --- | --- | --- |
| `execution_status` | `SUCCESS / FAIL / TIMEOUT / AUTH_EXPIRED / SKIPPED` | 程序与平台执行链是否完成 |
| `result_status` | `VALID / INVALID / UNCERTAIN / NOT_EVALUATED` | 结果正确性是否有确定性证据 |
| `final_status` | `PASS / FAIL / REVIEW / TIMEOUT / SKIPPED_*` | 最终业务处置状态 |

默认 `validation_mode=MANUAL_OR_MULTIMODAL`。因此即使 Console 成功且所有 DAG 为 success，也只证明执行链完成，不证明遥感/空间分析结果正确，默认得到：

```text
SUCCESS + UNCERTAIN + REVIEW
```

`review_queue.jsonl` 和 Excel 的“复核队列”工作表专门承接这些记录。大模型可作为后续可选多模态复核器，但不参与机械点击、代码提交一致性、HTTP、DAG 或基础执行成功判断。

如某条用例已有确定性 Oracle，可在 CSV 中显式设置：

- `EXECUTION_ONLY`：业务明确只验证执行链时使用
- `CONSOLE_REGEX`：用 `expected_console_regex` 验证 Console/executeCode 日志
- `GLOBE_CHANGED`：业务明确把 Globe 变化阈值定义为正确性规则时使用

不要为提高 PASS 数量而批量把用例改成 `EXECUTION_ONLY`。

## 登录失效与断点恢复

以下信号会触发 `AUTH_EXPIRED`：

- OGE API 返回 401/403
- 页面跳转到登录入口
- Monaco 与 Console 工作区同时消失

系统立即停止本批次，不继续点击后续算子。当前及剩余 READY 用例标记为 `SKIPPED_AUTH_EXPIRED`，已完成结果和证据不受影响。

`results.jsonl` 是追加式事实账本，`checkpoint.json` 记录最后持久化事件。重新登录后运行 `resume.bat`，系统复用原 Run 目录，跳过已终结记录，只重试 `SKIPPED_AUTH_EXPIRED` 或 `SKIPPED_BATCH_ABORTED`。恢复时会核对 CSV SHA-256 和原筛选参数，防止拿变化后的业务输入覆盖旧批次。

## 输出结构

每次新批次创建独立目录：

```text
output/runs/<run_id>/
├─ input/operators.csv
├─ run_metadata.json
├─ checkpoint.json
├─ preflight.json
├─ results.jsonl
├─ results.csv
├─ results.xlsx
├─ review_queue.jsonl
└─ cases/
   └─ 001_SpatialStats.../
      ├─ source.py
      ├─ result.json
      ├─ console.txt
      ├─ network.json
      ├─ network_summary.json
      ├─ trace.zip
      ├─ result_screenshot.png
      ├─ globe_result.png
      ├─ globe_before.png
      └─ attempts/
         └─ attempt_1/...
```

`source.py、result.json、console.txt、network.json、trace.zip、result_screenshot.png、globe_result.png` 对 PASS、FAIL、REVIEW、TIMEOUT 和所有 SKIPPED 都强制存在。无法取得真实页面或 Globe 时，会生成明确标注状态的占位证据，不会伪装成真实截图。

`result_screenshot.png` 为全页面截图，应同时看到代码区、Console、Globe 和当时页面状态；`globe_result.png` 只截结果 Canvas。

`results.csv` 与 `results.jsonl` 都是追加式事件账本，所以恢复运行后同一 `case_id` 可以出现新事件。`results.xlsx` 按每个 `case_id` 的最新事件折叠为 204 条当前结果，并保留原 Excel 的人工状态。截图、Console、Network、Trace 和证据目录均为可点击相对超链接。

批次结束时汇总必须满足：

```text
总数 = PASS + FAIL + REVIEW + TIMEOUT + 各类 SKIPPED
```

未完成批次会额外显示 `PENDING`，且“总数 - 全部最终状态”必须为 0。

## 常用参数

```bat
run.bat --start-id 1 --end-id 10
run.bat --contains Coverage.slope
run.bat --list-only
resume.bat
resume.bat --run-id 20260812_190528_942
```

## 注意事项

- 不要同时用普通 Edge 打开 `runtime/edge-profile`，否则持久化 Profile 可能被锁定。
- 正式批次启动后不等待人工登录；需要登录时使用独立 `login.bat`。
- 网站 DOM 或 API 契约变化时，先检查 `preflight.json、network.json、trace.zip`，不要改成固定坐标或 PyAutoGUI。
- 本包自检覆盖 CSV、204/189/15 统计、代码语法、HAR、DAG 绑定、判定、账本、Excel 和跳过证据。真实站点 Smoke Test 仍需在可访问 OGE 且具有登录态的目标 Windows 机器上执行。

