"""
clean_corpus.py - zhihu 语料清洗（确定性、可复现）

将 Code/zhihu_story_subset_120_20260815/ 清洗为 ..._clean/：
  1. 剥离完结/全文标记（【已完结】【完结】（已完结）（完）（全文）等）：纯标记行删除，
     带正文的保留正文（标题/开篇句不丢，如《冰洞》（已完结）→《冰洞》）
  2. 剔除头部作者签名/催更/声明/阅读提示行（前 3 行；manifest.author_name 精确匹配）
  3. 从尾部截断脚注/促销块（作者 CTA / END / 盐选 / 转载声明 / 读者催更提问 / URL 簇）
  4. 剔除章节/列表数字标记行（01、1、1.、1、）与零宽字符
  5. 碎片式行（词/标点单独成行）合并为完整段落，输出"一行一段落"

不修改原文件；规则区域限定（头部/尾部），避免误删正文（如"微信号""版权""评论区"会出现在故事正文中）。
对输出重跑应逐字节一致（幂等）。

用法:
    python test/clean_corpus.py                          # 默认清洗 zhihu_story_subset_120_20260815 -> ..._clean
    python test/clean_corpus.py --input <dir> --output <dir>
"""
import os
import re
import sys
import json
import shutil
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.Pre_pro.pre_processor import _clean_lines, _join_paragraphs

_BASE = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_INPUT = os.path.join(_BASE, "zhihu_story_subset_120_20260815")
DEFAULT_OUTPUT = os.path.join(_BASE, "zhihu_story_subset_120_20260815_clean")

HEAD_ZONE = 3
TAIL_ZONE = 25

# 完结/全文标记（全局剥离）：【已完结】【完结】[已完结，…]（已完结）（完结）（完）（全文）及行首"已完结/完结"
FINISH_MARK_RE = re.compile(
    r"【[^】]*(已完结|完结)[^】]*】|\[[^\]\n]*(已完结|完结)[^\]\n]*\]|"
    r"（已完结[～~]?）|\(已完结[～~]?\)|（完结）|（完）|（全文）|\(完结\)|\(完\)|\(全文\)|"
    r"^已完结[，,、~～]?|^完结[，,、~～]?|这篇盐选啦宝子们文末有链接"
)
# 头部纯噪音行（仅前 HEAD_ZONE 个非空行）：作者签名/催更/声明/阅读提示
HEAD_NOISE = re.compile(
    r"合作请私信|欢迎推文|请勿超长|请勿全文转载|请勿推付费|推文勿放|勿放付费|禁止(转载|搬运)|谢绝转载|"
    r"点赞催更|^请各位|^慎入|^本文三观不正|盐选文不能放结局|自产美味粮|感谢推文|以下原答案|"
    r"主页置顶|^完结免费|感到不适|及时退出"
)
# 硬脚注起始：在尾部区域命中即从该行截断
HARD_FOOTER = re.compile(
    r"－?END－?|全文完|（完）|\(完\)|已完结|完结啦|完结了|完结链接|已更完|全文(已经)?更完|"
    r"^作者[｜|:]|^欢迎关注|^喜欢(的话|的朋友)|谢谢.*(点赞|支持|完结)|"
    r"盐选|全文链接|全文已出|链接如下|这个链接|下方链接|戳链接|链接里|链接(即可|观看|戳|啦|：|:)|"
    r"移步(盐选|全文|阅读|链接)|点下面|点卡片|传送门|看后续|看全文|观看全文|"
    r"点击下方|下方完结|戳(这里|下方)|后续(见|戳)|这个回答不更了|全文更新在|答案在评论区|"
    r"^编辑于|^发布于|^修改于|公众号|私信|转载|喜欢就(点|支持)|https?://|www\.zhihu"
)
# 促销块特征行：读者催更提问 / "下方完结文"（尾部截断时向上吸收）
PROMO_START_RE = re.compile(r"^有没有[^。？\n]{0,40}的小说[？?]|下方完结文")
# 纯 emoji/心形行（如 ❤️❤️❤️）
HEART_ONLY = re.compile(r"^[\u2764\ufe0f\s‼️\u26a0\ufe0f]+$")
# 行内 CTA 尾巴（"欲知后事如何"是经典作者引流句式，仅在尾部窗口生效）
LINE_TAIL_CTA_RE = re.compile(r"欲知后事如何.*$")
# 行级噪音（仅在尾部窗口生效）：作者"答案在评论区"备注
LINE_NOISE = re.compile(r"答案在评论区")
# URL 起始行（含裸 https://）与其 ASCII 续行（如 mparticle.uc.cn/story.h / 3716）
URL_LINE_RE = re.compile(r"^https?://\S*$")
URL_FRAG_LINE_RE = re.compile(r"^[A-Za-z0-9_./?&=:%#\-,~]{3,}$")
# 长行且带引号 ≈ 故事对话（与 CTA 混排的行不当作脚注起点，避免切掉正文结尾）
def _looks_like_dialogue(ln: str) -> bool:
    return len(ln) > 80 and any(q in ln for q in ("”", "“", "「", "」"))
# URL 碎片行（促销块中 https:// 被拆成多行）
URL_FRAG_RE = re.compile(r"^https?://|^www\.|^zhihu\.com|^\d{3,6}$")
# 短括号标题（促销块条目头，如 【打赏】）；仅在脚注命中时向上吸收
SHORT_BRACKET_RE = re.compile(r"^【[^】]{1,25}】$")


def clean_text(raw: str, author_name: str = "") -> tuple[str, dict]:
    """清洗单篇文本，返回 (清洗后文本, 统计)。"""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    n = len(lines)
    stats = {
        "original_lines": n,
        "head_removed": 0,
        "truncated": False,
        "truncated_line": "",
        "truncated_lines": 0,
        "noise_removed": 0,
        "paragraphs": 0,
        "cleaned_chars": 0,
        "fallback": False,
    }

    # 1. 头部噪音（仅前 HEAD_ZONE 个"保留行"之前的区域）：manifest 作者行精确匹配 + 纯噪音行。
    #    先于标记剥离执行，避免"完结免费"被剥离成"免费"后漏检。
    kept, skipped, head_count = [], 0, 0
    for ln in lines:
        if head_count < HEAD_ZONE and (ln == author_name or HEAD_NOISE.search(ln)):
            skipped += 1
            continue
        head_count += 1
        kept.append(ln)
    stats["head_removed"] = skipped
    stats["noise_removed"] += skipped
    lines = kept

    # 2. 完结/全文标记剥离（全局，覆盖正文中间的碎片标记，如《枕眠》（已完结～）跨行碎片）
    kept = []
    for ln in lines:
        s = FINISH_MARK_RE.sub("", ln).strip()
        if s != ln:
            if not s:
                stats["noise_removed"] += 1
                continue
            ln = s
        kept.append(ln)
    lines = kept

    # 3. 尾部脚注/促销块截断：迭代重扫尾部窗口（覆盖长促销块），命中即截断，
    #    并向上吸收紧邻的 URL 碎片/括号标题/读者催更提问行（如 【打赏】+ 拆行 URL）。
    while len(lines) >= 5:
        tail_start = max(0, len(lines) - TAIL_ZONE)
        hit = None
        for i in range(tail_start, len(lines)):
            ln = lines[i]
            if (HARD_FOOTER.search(ln) or HEART_ONLY.match(ln)) and not _looks_like_dialogue(ln):
                hit = i
                break
        if hit is None:
            break
        start = hit
        while start > 0 and (URL_FRAG_RE.match(lines[start - 1]) or SHORT_BRACKET_RE.match(lines[start - 1]) or PROMO_START_RE.search(lines[start - 1])):
            start -= 1
        stats["truncated"] = True
        stats["truncated_line"] = lines[start][:60]
        stats["truncated_lines"] += len(lines) - start
        lines = lines[:start]

    # 4. 行级噪音：行内 CTA 尾巴仅尾部窗口；"答案在评论区"备注整行剔除（全局，
    #    避免其与正文拼接成"16、这个答案在评论区17、……"后二次清洗才被截断，破坏幂等）
    if len(lines) > TAIL_ZONE:
        head, tail = lines[:-TAIL_ZONE], lines[-TAIL_ZONE:]
    else:
        head, tail = [], lines
    cleaned_tail = []
    for ln in tail:
        s = LINE_TAIL_CTA_RE.sub("", ln).rstrip()
        if s:
            cleaned_tail.append(s)
        else:
            stats["noise_removed"] += 1
    lines = head + cleaned_tail
    kept = []
    for ln in lines:
        if LINE_NOISE.search(ln):
            stats["noise_removed"] += 1
            continue
        kept.append(ln)
    lines = kept
    scrubbed = []
    i = 0
    while i < len(lines):
        if URL_LINE_RE.match(lines[i]):
            stats["noise_removed"] += 1
            i += 1
            while i < len(lines) and URL_FRAG_LINE_RE.match(lines[i]):
                stats["noise_removed"] += 1
                i += 1
            continue
        scrubbed.append(lines[i])
        i += 1
    lines = scrubbed

    # 5+6. 剔除数字标记/零宽字符，碎片行合并为段落
    cleaned_lines = _clean_lines("\n".join(lines))
    stats["noise_removed"] += len(lines) - len(cleaned_lines)
    paragraphs = _join_paragraphs(cleaned_lines)
    if not paragraphs:  # 兜底：清洗后为空则保留原文
        paragraphs = [raw.strip()]
        stats["fallback"] = True
    stats["paragraphs"] = len(paragraphs)
    stats["cleaned_chars"] = sum(len(p) for p in paragraphs)
    return "\n".join(paragraphs) + "\n", stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not os.path.isdir(args.input):
        print(f"输入目录不存在: {args.input}")
        return 1

    # manifest.author_name 用于精确剔除头部作者行（仅头 3 行内出现）
    author_by_rel = {}
    manifest_path = os.path.join(args.input, "manifest.json")
    if os.path.exists(manifest_path):
        for entry in json.load(open(manifest_path, encoding="utf-8")):
            rel = entry.get("txt_file", "").replace("\\", "/")
            author_by_rel[rel] = entry.get("author_name", "")

    if os.path.exists(args.output):
        shutil.rmtree(args.output)
    os.makedirs(args.output)

    report = []
    total_noise = 0
    for root, dirs, files in os.walk(args.input):
        for fn in sorted(files):
            if not fn.endswith(".txt"):
                continue
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, args.input).replace("\\", "/")
            rel_root = os.path.dirname(rel)
            out_dir = os.path.join(args.output, rel_root) if rel_root else args.output
            os.makedirs(out_dir, exist_ok=True)
            raw = open(src, encoding="utf-8").read()
            cleaned, stats = clean_text(raw, author_name=author_by_rel.get(rel, ""))
            with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as f:
                f.write(cleaned)
            total_noise += stats["noise_removed"]
            report.append({"file": rel, **stats})
            flag = "  →截断" if stats["truncated"] else ""
            print(f"  {rel:<45} 行 {stats['original_lines']:>5} → 段 {stats['paragraphs']:>4}"
                  f" (噪音 -{stats['noise_removed']:>3}){flag}")

    # 复制 manifest（txt_file 相对路径与清洗目录结构一致，batch_run 元数据注入仍可用）
    for meta in ("manifest.json", "manifest.csv"):
        src = os.path.join(args.input, meta)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(args.output, meta))

    with open(os.path.join(args.output, "clean_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
        f.write("\n")

    n_files = len(report)
    n_trunc = sum(1 for r in report if r["truncated"])
    print(f"\n共清洗 {n_files} 篇，截断脚注 {n_trunc} 篇，共剔除噪音 {total_noise} 行。")
    print(f"输出: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())