"""
题材 Function 提取与对比
读取 --out-dir 下的 functions_<category>.jsonl / bank_<category>.jsonl 快照，
输出每题材 Function 清单与跨题材近义组，并生成 genre_functions_summary.md。

用法:
    python test/genre_extract.py --out-dir data/genre_functions
"""
import sys, os, json, glob, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Embedding.embedding import Embedder
from Agent.Inducer.confidence import max_definition_similarity, NEAR_DUP_THRESHOLD


def load_jsonl(path: str) -> list[dict]:
    rows = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows


def supporting_stats(func: dict, bank_index: dict) -> tuple[int, int]:
    """返回 (可解析的 supporting obs 数, 涉及的不同 story 数)"""
    obs_ids = func.get("supporting_obs_ids", [])
    present = [oid for oid in obs_ids if oid in bank_index]
    stories = {bank_index[oid].get("story_id", "?") for oid in present}
    return len(present), len(stories)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="data/genre_functions")
    parser.add_argument("--threshold", type=float, default=NEAR_DUP_THRESHOLD)
    args = parser.parse_args()

    func_files = sorted(glob.glob(os.path.join(args.out_dir, "functions_*.jsonl")))
    if not func_files:
        print(f"没有找到 {os.path.join(args.out_dir, 'functions_*.jsonl')} 快照")
        return 1

    embedder = Embedder()
    genres = []
    for fp in func_files:
        tag = os.path.basename(fp)[len("functions_"):-len(".jsonl")]
        funcs = load_jsonl(fp)
        bank_index = {
            o["obs_id"]: o
            for o in load_jsonl(os.path.join(args.out_dir, f"bank_{tag}.jsonl"))
        }
        genres.append({"tag": tag, "funcs": funcs, "bank": bank_index})

    lines = ["# 题材 Function 对比摘要", ""]
    for g in genres:
        lines.append(f"## {g['tag']}（{len(g['funcs'])} 个 Function）")
        if not g["funcs"]:
            lines.append("（空）")
            lines.append("")
            continue
        for f in g["funcs"]:
            n_obs, n_stories = supporting_stats(f, g["bank"])
            lines.append(
                f"- **{f.get('function_name', 'N/A')}** "
                f"(conf={f.get('confidence', 0):.3f}, "
                f"supporting={n_obs} obs / {n_stories} 故事)"
            )
            lines.append(f"  - 定义: {f.get('definition', '')}")
        lines.append("")

    lines.append("## 跨题材近义组")
    cross = []
    for i in range(len(genres)):
        for j in range(i + 1, len(genres)):
            for fi in genres[i]["funcs"]:
                for fj in genres[j]["funcs"]:
                    sim = max_definition_similarity(
                        fi.get("definition", ""), [fj], embedder
                    )
                    if sim > args.threshold:
                        cross.append(
                            (genres[i]["tag"], fi["function_name"],
                             genres[j]["tag"], fj["function_name"], sim)
                        )
    if cross:
        for a, fa, b, fb, sim in cross:
            lines.append(f"- `{fa}` ({a}) ≈ `{fb}` ({b}) sim={sim:.3f}")
    else:
        lines.append("（无）")
    lines.append("")

    text = "\n".join(lines)
    print(text)
    md_path = os.path.join(args.out_dir, "genre_functions_summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"\n摘要已写入 {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
