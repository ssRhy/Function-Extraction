---
name: function-extraction-bootstrap
description: 只在 Function-Extraction 项目中启动并核验 Bootstrap 根库阶段；自动完成其内部的 Function 提取和 Pattern，不运行 Evolve 或 Story。
---

# Bootstrap 阶段

只执行 Bootstrap，不继续调用 Evolve 或 Story。Bootstrap 内部的 Function 提取、评估修订和 Pattern 直接自动完成，不要在中间请求用户确认。命令从 `Code/` 目录执行：

```bash
cd /Users/hy/Desktop/code/Function-Extraction/Code
.venv/bin/python -X utf8 -m StoryCLI library status
```

准备 Bootstrap 语料时，应提醒用户输入多个不同题材的故事，不要只使用单一题材。建议总量至少约 60 篇；若使用当前五个题材，最好每个题材约 12 篇。若数量少于该规模或题材过于集中，应先提示可能无法通过 diversity、evidence 和 Pattern 发布门禁，但不替用户擅自抽取或改选批次。

如果用户只是询问命令，不要启动 LLM；如果用户要求运行且已给出语料目录，直接执行：

```bash
.venv/bin/python -X utf8 -m StoryCLI bootstrap \
  --input <bootstrap语料目录>
```

要求输入至少两个 UTF-8 `.txt` 故事。该命令会自动完成 Function 提取、评估修订、根 Snapshot 和 Pattern；成功后根 Snapshot 自动成为 serving，但不会启动 Evolve 或 Story。不要再单独调用 Pattern。

只有用户的请求明确包含“清空/重建正式库”时才增加 `--reset-formal`；不需要为 Pattern 再次确认。不要与其他 Bootstrap/Evolve 并行运行。

完成后检查终端输出的 `function_run`、`run_result`、`snapshot_id`、Pattern 状态和 serving 状态。PASS/SUCCESS 说明流程和数据门禁通过，不单独代表文学质量。失败时保留运行目录和日志，不为了制造 PASS 重复消耗 LLM 请求。
