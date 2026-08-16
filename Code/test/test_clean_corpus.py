"""clean_corpus.py 清洗回归测试（确定性、幂等、头部剥离、尾部截断、促销残留）"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clean_corpus import clean_text


def norm(t: str) -> str:
    return t.replace("\r\n", "\n")


def run(raw, author_name=""):
    cleaned, stats = clean_text(raw, author_name=author_name)
    return norm(cleaned), stats


def test_head_marker_strip_keeps_content():
    # 【已完结】前缀的正文行：剥离标记、保留正文，不能整行删除
    cleaned, stats = run("【已完结】一夜之间，我和小病娇双双住院治疗。\n街头巷尾人尽皆知。\n")
    assert cleaned.startswith("一夜之间，我和小病娇双双住院治疗。\n"), cleaned[:60]
    assert "已完结" not in cleaned
    print("头部标记剥离保留正文: OK")


def test_head_pure_marker_removed():
    cleaned, stats = run("（已完结）\n正文开始。\n")
    assert cleaned == "正文开始。\n", cleaned
    print("纯标记行删除: OK")


def test_head_title_bracket_kept():
    cleaned, stats = run("《冰洞》（已完结）\n正文开始。\n")
    assert cleaned.startswith("《冰洞》"), cleaned[:30]
    assert "已完结" not in cleaned
    print("书名号标题保留: OK")


def test_head_author_and_slogan_removed():
    cleaned, stats = run("yueyang月牙\n人生苦短，笑得开心点（合作请私信）\n正文开始。\n", author_name="yueyang月牙")
    assert cleaned == "正文开始。\n", cleaned
    assert stats["head_removed"] == 2, stats
    print("作者行与签名行剔除: OK")


def test_head_pure_noise_lines_removed():
    cases = [
        "慎入‼️本文三观不正，男主心理病态。\n正文。\n",
        "点赞催更，感恩支持\n正文。\n",
        "谢绝转载！！\n以下原答案\n正文。\n",
        "请各位宝子单独留个评论，上架会统一踢❤️\n正文。\n",
        "完结免费，介个写了玩哒。\n正文。\n",
    ]
    for raw in cases:
        cleaned, stats = run(raw)
        assert cleaned == "正文。\n", (raw, cleaned)
    print("纯噪音行剔除: OK")


def test_finish_mark_global_strip():
    # 正文中间的碎片标记（《枕眠》（已完结～）跨行）也要剥离
    cleaned, stats = run("《枕眠》\n（\n已完结～\n）\n我重生在反派 boss 的床上。\n")
    assert "已完结" not in cleaned, cleaned
    assert "我重生在反派 boss 的床上。" in cleaned
    print("正文中间碎片标记剥离: OK")


def test_tail_promo_question_absorbed():
    # 尾部促销块：读者催更提问 + 下方完结文 + URL 簇，整块截断
    raw = (
        "故事正文最后一句。\n"
        "有没有男女主互动很甜，越看越上头的小说？\n"
        "下方完结文⏬\n"
        "【打赏】\n"
        "https://www.\n"
        "zhihu.com/answer/205723\n"
        "3716\n"
        "【暧昧】\n"
        "结婚时我的丈夫和我说好各玩各的。\n"
        "https://www.\n"
        "zhihu.com/answer/176329\n"
        "1276\n"
    )
    cleaned, stats = run(raw)
    assert stats["truncated"], stats
    for kw in ("有没有男女主", "下方完结文", "https://", "【打赏】", "【暧昧】"):
        assert kw not in cleaned, kw
    assert cleaned == "故事正文最后一句。\n", cleaned
    print("尾部促销块截断: OK")


def test_cta_tail_only_in_tail_window():
    # "欲知后事如何" CTA 尾巴只在尾部窗口剥离；正文中段不受影响
    lines = [f"第{i}行正文。" for i in range(30)]
    lines[2] = "中段出现欲知后事如何，且听下回分解。"
    lines.append("结尾欲知后事如何，请店下方链接。")
    cleaned, _ = run("\n".join(lines) + "\n")
    out = cleaned.splitlines()
    assert any("中段出现欲知后事如何，且听下回分解。" in l for l in out), out
    assert not any("结尾欲知后事如何" in l for l in out), out[-1]
    print("CTA 尾巴限尾部窗口: OK")


def test_author_name_removed():
    cleaned, stats = run("南迦巴瓦遇见亚丁\n\u200b\n请各位宝子单独留个评论。\n最近，我总觉得屋里多了一个人。\n", author_name="南迦巴瓦遇见亚丁")
    assert cleaned == "最近，我总觉得屋里多了一个人。\n", cleaned
    print("manifest 作者行精确匹配: OK")


def test_idempotent():
    samples = [
        "【已完结】一夜之间，我和小病娇双双住院治疗。\n街头巷尾人尽皆知。\n",
        "（已完结）我惹老公生气了，去公司和他道歉。\n一进门我便委屈道：“你理理我吧。”\n",
        "《冰洞》（已完结）\n在南极地下冰湖的湖水样本中，科研人员发现了一组全新未知的生物基因。\n",
        "故事正文。\n有没有男女主互动很甜，越看越上头的小说？\n下方完结文⏬\n【打赏】\nhttps://www.\nzhihu.com/answer/1\n2\n",
        "《枕眠》\n（\n已完结～\n）\n我重生在反派 boss 的床上。\n",
    ]
    for raw in samples:
        cleaned, _ = run(raw)
        again, _ = run(cleaned)
        assert again == cleaned, (raw, cleaned, again)
    print("幂等性: OK")


def test_answer_in_comments_note_removed_global():
    # "答案在评论区" 备注行全局剔除，避免其与下一行拼接成"16、…17、…"破坏幂等
    raw = (
        "1.清晨起床，发现手机里多了一张我睡觉的照片。\n"
        "（这个答案在评论区）\n"
        "2.我一直都在母亲帮他处理尸体。\n"
        "16、这个答案在评论区\n"
        "17、一直都是母亲在帮他处理尸体……\n"
        "（42以后的答案在评论区，可自行寻找）\n"
    )
    cleaned, stats = run(raw)
    assert "答案在评论区" not in cleaned, cleaned
    again, _ = run(cleaned)
    assert again == cleaned
    print("答案在评论区备注全局剔除: OK")


def test_report_schema():
    # M9：fallback 键始终存在且为布尔，noise_removed 与 paragraphs 分离
    cleaned, stats = run("【已完结】\n正文开始。\n")
    for key in ("original_lines", "head_removed", "truncated", "truncated_line", "truncated_lines",
                "noise_removed", "paragraphs", "cleaned_chars", "fallback"):
        assert key in stats, key
    assert isinstance(stats["fallback"], bool), stats["fallback"]
    assert stats["noise_removed"] >= 1, stats
    print("报告 schema 一致: OK")


if __name__ == "__main__":
    test_head_marker_strip_keeps_content()
    test_head_pure_marker_removed()
    test_head_title_bracket_kept()
    test_head_author_and_slogan_removed()
    test_head_pure_noise_lines_removed()
    test_finish_mark_global_strip()
    test_tail_promo_question_absorbed()
    test_cta_tail_only_in_tail_window()
    test_author_name_removed()
    test_idempotent()
    test_answer_in_comments_note_removed_global()
    test_report_schema()
    print("所有清洗测试通过!")