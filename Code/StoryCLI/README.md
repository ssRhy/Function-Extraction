# StoryCLI 命令行使用指南

StoryCLI 是本项目面向用户的命令行入口。公开使用分成三个独立命令：

```text
bootstrap：文本 → Function → Pattern → serving
evolve：新文本 → Function 增量 → Pattern 增量 → candidate
story：用户要求 → serving → Outline → Story
```

用户不需要填写 `namespace` 或 Snapshot ID。Bootstrap 和 Evolve 是知识库命令，Story 是知识库消费命令。

如果不想直接使用命令行，可启动项目自带的轻量 Tkinter 窗口：

```bash
cd /path/to/Function-Extraction/Code
.venv/bin/python -X utf8 -m StoryUI
```

窗口中的 1、2、3 分别对应 Bootstrap、Evolve 和生成文章。生成文章时，窗口只调用现有结构化 LLM 识别题材，操作类型由用户已选择的入口固定；程序去除原文开头已有的题材别名，只补一个规范前缀，再以固定参数启动 StoryCLI；模型不会生成或执行任意 shell 命令。生成文章可选择 Dynamic Planner 或 Published Pattern；Evolve 固定在成功后执行 `--promote`。Bootstrap 至少需要两个 `.txt` 故事，单篇新故事应使用 Evolve；“归档并重建正式库”默认关闭，勾选后还需要确认。

## 1. 准备环境

以下命令从仓库的 `Code/` 目录执行。建议始终使用项目自己的 `.venv/bin/python`，不要混用 Conda 或系统 Python：

```bash
cd /path/to/Function-Extraction/Code

# 如果还没有虚拟环境
python3.10 -m venv .venv

.venv/bin/python -m pip install sentence-transformers chromadb openai pydantic langgraph
.venv/bin/python -m pip install --no-deps --target vendor \
  langgraph-checkpoint-sqlite sqlite-vec aiosqlite
```

本项目的 LLM 客户端当前从以下文件读取 DeepSeek API Key：

```text
Code/FunctionExtract_Agent/.env
```

该文件只放 API Key 本身，不要写成 `OPENAI_API_KEY=...`。不要把这个文件提交到公开仓库。

Embedding 使用本地缓存的 `BAAI/bge-small-zh-v1.5`，首次运行前请确认该模型已经存在于本机缓存；当前代码强制离线加载模型。

## 2. 准备输入文本

准备两个目录：

```text
my_data/
├── bootstrap/
│   ├── story_001.txt
│   ├── story_002.txt
│   └── ancient/
│       └── story_003.txt
└── evolve/
    ├── new_story_001.txt
    └── new_story_002.txt
```

- `bootstrap`：用于建立新的 Function 根库，支持单个 `.txt` 文件、目录和多层目录递归收集。
- `evolve`：用于基于本次 Bootstrap 结果增量加入的新故事，同样支持文件和递归目录。
- 文件编码使用 UTF-8，扩展名必须是 `.txt`。
- Bootstrap 应准备多篇有共同叙事结构的故事；只有一篇时通常没有足够的跨故事证据形成可发布 Pattern。
- Evolve 应输入真正的新文本。若同一个 `story_id` 已经存在但文本内容发生变化，系统会拒绝写入，以保护版本一致性。

## 3. 三个独立命令

### 3.1 Bootstrap：建立 Function 根库

Bootstrap 内部先从文本提取 Function，再运行 Pattern，成功后自动把根 Snapshot 设为 serving：

```bash
cd /path/to/Function-Extraction/Code

.venv/bin/python -X utf8 -m StoryCLI bootstrap \
  --input /path/to/my_data/bootstrap
```

`--input` 可以是单个 `.txt` 文件，也可以是目录；该参数可以重复。

### 3.2 Evolve：增量演化 Function 和 Pattern

Evolve 默认读取当前 serving Snapshot 作为父版本，成功后只生成候选 Snapshot：

```bash
.venv/bin/python -X utf8 -m StoryCLI evolve \
  --input /path/to/my_data/evolve
```

如果确认候选版本可以成为后续默认版本，加 `--promote`；不需要填写 Snapshot ID：

```bash
.venv/bin/python -X utf8 -m StoryCLI evolve \
  --input /path/to/my_data/evolve \
  --promote
```

不加 `--promote` 时，当前 serving 保持不变。

### 3.3 Story：根据用户要求生成故事

Story 默认读取当前 serving Snapshot，自动完成 Pattern 选择、Outline 和 Story：

```bash
.venv/bin/python -X utf8 -m StoryCLI story generate \
  --request "古风仙侠：写一个雨夜寻药故事，结局必须完成真相揭示"
```

较长的要求可以使用文件：

```bash
.venv/bin/python -X utf8 -m StoryCLI story generate \
  --request-file /path/to/story_request.txt
```

`--request` 和 `--request-file` 只能二选一。

### 第一次建立全新正式库

如果 Bootstrap 需要清空当前正式 Knowledge DB、Registry、Bank、Ontology Snapshot 和 checkpoint，显式增加 `--reset-formal`：

```bash
.venv/bin/python -X utf8 -m StoryCLI bootstrap \
  --reset-formal \
  --input /path/to/my_data/bootstrap
```

重置前的正式资产会移动到：

```text
Code/data/formal_archives/<时间戳>/
```

这是可恢复归档，不会永久删除。默认不带 `--reset-formal`，以避免误清理已有正式数据；执行重置时不要同时运行另一条 Bootstrap/Evolve 命令。

## 4. 创作要求和题材识别

题材从创作要求中确定，不需要另传 `--genre`。请求中必须命中且只命中一个方向：

| 题材 | 可用关键词 |
|---|---|
| 悬疑惊悚 | `悬疑`、`惊悚`、`推理`、`侦探` |
| 古风仙侠 | `古风`、`仙侠`、`修仙`、`穿越` |
| 现代情感 | `现代情感`、`都市情感`、`言情`、`爱情` |
| 末世科幻 | `末世`、`科幻`、`废土` |
| 现实家庭职场 | `现实家庭`、`家庭`、`职场`、`婚姻` |

未命中或同时命中多个题材时，命令会在调用 LLM 前直接报错。建议把题材写在要求开头，例如：

```text
现代情感：写一次克制的家庭关系修复，结局要有可观察的解决行动。
```

## 5. 运行产物

Bootstrap 和 Evolve 默认输出到：

```text
Code/data/story_cli/functions/<时间戳>/
```

Story 默认输出到：

```text
Code/data/pipeline_runs/<时间戳>/
```

主要产物如下：

```text
functions/<时间戳>/function_run.json
pipeline_runs/<时间戳>/
├── outline/*.json
├── story/*.json
├── story/*.md
└── pipeline_manifest.json
```

Bootstrap/Evolve 终端会打印 `function_run` 路径和 Snapshot 信息；Story 终端会打印 `pipeline_manifest` 路径。

Story 默认使用 serving，不会自动读取未 promote 的 Evolve 候选。先审查候选，再在 Evolve 命令中增加 `--promote`，即可让它成为后续 Story 的默认版本。

也可以指定 Story 输出目录：

```bash
.venv/bin/python -X utf8 -m StoryCLI story generate \
  --request "末世科幻：写一段废土求生故事" \
  --out-dir data/pipeline_runs/my_first_story
```

## 6. 查看正式库状态

只读查看当前正式库和 serving 指针：

```bash
.venv/bin/python -X utf8 -m StoryCLI library status
```

公开命令不要求用户手动填写 Snapshot。只有调试或维护正式版本时，才需要查看项目根 README 中的分阶段高级命令。

## 7. 失败时怎么处理

- `输入路径不存在`：检查 `bootstrap --input` 或 `evolve --input` 路径是否正确。
- `输入中没有 .txt 文件`：确认目录中存在 UTF-8 `.txt` 文件，而不是只放 `.md` 或其他格式。
- `用户要求中未识别题材`：在要求中加入一个题材关键词。
- `用户要求命中多个题材`：删除冲突题材，只保留一个方向。
- `故事版本已存在且人物画像不一致`：Evolve 使用了已登记的 `story_id`，请换成真正的新故事或恢复其原始内容。
- 出现 `transformers`、`torch` 或 `sentence_transformers` 导入错误：确认命令使用的是 `.venv/bin/python`，并在同一个虚拟环境中重新安装依赖；不要把 Conda 的 `python` 与项目 `.venv` 混用。
- Outline 校验失败：系统会保留当前运行目录中的大纲，但不会启动正文；先根据报错检查创作要求和正式 Pattern。
- LLM 或网络请求失败：保留当前运行目录和终端错误信息，确认 API Key、网络和模型服务状态后再重试。不要删除正式归档目录。

## 8. 查看命令帮助

```bash
.venv/bin/python -X utf8 -m StoryCLI --help
.venv/bin/python -X utf8 -m StoryCLI bootstrap --help
.venv/bin/python -X utf8 -m StoryCLI evolve --help
.venv/bin/python -X utf8 -m StoryCLI story generate --help
```
