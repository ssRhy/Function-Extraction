---
name: function-extraction-evolve
description: 只在 Function-Extraction 项目中启动并核验 Evolve 增量阶段；自动完成 Function 增量、Pattern 并切换新 Snapshot 为 serving，不运行 Bootstrap 或 Story。
---

# Evolve 阶段

只执行 Evolve，不继续调用 Bootstrap 或 Story。Evolve 内部的 Function 增量、Pattern 和重试边界直接自动完成，不要在中间请求用户确认。先读取当前 serving Snapshot：

```bash
cd /Users/hy/Desktop/code/Function-Extraction/Code
.venv/bin/python -X utf8 -m StoryCLI library status
```

如果用户只是询问命令，不要启动 LLM；如果用户要求运行且已给出新语料目录，直接执行：

```bash
.venv/bin/python -X utf8 -m StoryCLI evolve \
  --input <evolve语料目录>
```

Evolve 默认以当前 serving Snapshot 为父版本，内部自动完成 Function 增量和 Pattern 增量；成功通过现有发布门禁后直接将新 Snapshot 切换为 serving。不要单独再调用 Pattern，也不要询问是否继续或是否 promote。

输入必须是真正的新 UTF-8 `.txt` 故事；重复 `story_id` 且内容变化会被拒绝。不要使用 Bootstrap 的 `--reset-formal`，不要与其他 Bootstrap/Evolve 并行运行。

需要进程级重试和阶段超时时，使用项目已有的一条龙调度入口 `FunctionCoordinator_Agent`，它会自动执行 `Evolve → Pattern`。该底层入口用于隔离候选验证，默认不切换正式 serving；普通 Evolve 使用上面的公开 `StoryCLI` 入口：

```bash
.venv/bin/python -X utf8 -m FunctionCoordinator_Agent \
  --mode evolve \
  --corpus <evolve语料目录> \
  --namespace <父Snapshot的namespace> \
  --base-snapshot <当前serving_snapshot_id> \
  --knowledge-db data/knowledge/story_knowledge.db \
  --snapshot-root data/ontology_snapshots
```

除非用户明确要求这个隔离调度入口，否则不要用它替代默认 serving 的公开 Evolve；避免重复启动同一阶段。

完成后检查 `function_run`、`run_result`、父/新 `snapshot_id`、Pattern 状态，并确认 serving_snapshot_id 已等于新 Snapshot。失败时保留运行目录和日志，不切换 serving，不直接修改 immutable Snapshot。
