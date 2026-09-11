---
name: function-extraction-story
description: 只在 Function-Extraction 项目中根据用户要求启动并核验 Story 生成阶段；自动完成 Pattern、Outline 和正文，不运行 Bootstrap 或 Evolve。
---

# Story 阶段

只执行 Story，不调用 Bootstrap 或 Evolve。开始生成前，如果用户没有明确指定规划方式，先询问一次：

> 这次使用哪种方式生成？
> - **Pattern**：使用 serving Snapshot 中已发布的结构，结构更稳定、可控。
> - **Dynamic**：先根据用户要求生成 Seed，再动态组合兼容的 Function，灵活性更高。

用户选择后，明确使用对应的 `--planner-mode`；Outline 和正文阶段直接自动完成，不要再请求中间确认。先读取可用的 serving Snapshot：

```bash
cd /Users/hy/Desktop/code/Function-Extraction/Code
.venv/bin/python -X utf8 -m StoryCLI library status
```

如果用户只是询问命令，不要启动 LLM；如果用户要求生成且已给出创作要求，直接执行：

```bash
.venv/bin/python -X utf8 -m StoryCLI story generate \
  --request "<包含唯一题材关键词的创作要求>"
```

该命令只消费 serving Snapshot，自动完成选定规划方式、Outline 和 Story；不会运行 Bootstrap 或 Evolve。不要把 Outline 或 Story 拆成额外的人工确认步骤。较长要求可改用 `--request-file <文件>`，与 `--request` 二选一。

Pattern 选择：

```bash
.venv/bin/python -X utf8 -m StoryCLI story generate \
  --request "<创作要求>" \
  --planner-mode published
```

Dynamic 选择：

```bash
.venv/bin/python -X utf8 -m StoryCLI story generate \
  --request "<创作要求>" \
  --planner-mode dynamic
```

只有用户明确指定某个 Snapshot 时才传 `--snapshot-id`。

完成后检查输出目录中的 `pipeline_manifest.json`、Outline 校验、Story Validator 和最终正文。自动校验通过只代表机械门禁通过，仍需单独审查正文语义与结局是否兑现用户要求。
