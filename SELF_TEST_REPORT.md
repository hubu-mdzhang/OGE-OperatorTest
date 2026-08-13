# V2 自检报告

自检日期：2026-08-12

## 结论

- Python 源码编译：通过
- Excel → CSV：通过
- 业务统计：204 总条、189 可执行、15 缺代码/英文名
- 重复 case_id：0
- 重复英文名：1 组，`Feature Model Regress`（已告警，按 case_id 独立）
- 189 份代码 Python 语法：通过
- HAR：`executeCode=200`，目标 DAG=3，逐 ID success=3
- 非浏览器自动化测试：14 passed
- 浏览器测试：2 skipped（当前构建容器无 Chromium 二进制；目标机 `setup.bat` 会安装）
- 204 条无浏览器干跑：204 条 JSONL、204 条 CSV 数据行、204 行 Excel 结果、204 个算子证据目录
- 干跑状态：`SKIPPED_FILTERED=189`、`SKIPPED_NO_CODE=15`，总数对账为 0
- `results.xlsx`：三工作表可打开，无公式错误；已检查汇总、测试结果和复核队列布局

## 仍需目标环境验证

当前环境未使用真实 OGE 登录态，因此交付后应在 Windows/Edge 上先运行：

```bat
login.bat
run.bat --start-id 1 --end-id 1
```

确认真实页面 Selector、Monaco Model、Console、executeCode/executeDag 和 Globe 截图均正常后，再扩大批量范围。

