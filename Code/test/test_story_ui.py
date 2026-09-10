"""StoryUI 的命令映射、进程协议和正文读取测试。"""

import json
import os
import queue
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import StoryUI.app as app
from StoryUI.router import GenrePlan, RoutePlan, route_request


def test_build_command_maps_three_operations_without_shell(tmp_path):
    input_path = tmp_path / "中文 故事.txt"

    assert app.build_command("bootstrap", input_path, reset_formal=True) == [
        sys.executable, "-u", "-X", "utf8", "-m", "StoryCLI",
        "bootstrap", "--input", str(input_path), "--reset-formal",
    ]
    assert app.build_command("evolve", input_path)[-3:] == [
        "--input", str(input_path), "--promote",
    ]
    assert app.build_command(
        "story", "古风仙侠：写一个完整故事", genre="02_古风仙侠",
    )[-2:] == [
        "--planner-mode", "dynamic",
    ]
    request_index = app.build_command(
        "story", "古风仙侠：写一个完整故事", genre="02_古风仙侠",
    ).index("--request")
    assert app.build_command(
        "story", "银行家和画家的相爱故事", genre="03_现代情感",
    )[request_index + 1] == "现代情感：银行家和画家的相爱故事"
    assert app.build_command(
        "story", "情感：在战场上两位对手相爱了，但是却爱而不得", genre="03_现代情感",
    )[request_index + 1] == "现代情感：在战场上两位对手相爱了，但是却爱而不得"
    assert app.build_command(
        "story", "现代情感：情感类:在战场上两位对手相爱了，但是却爱而不得", genre="03_现代情感",
    )[request_index + 1] == "现代情感：在战场上两位对手相爱了，但是却爱而不得"
    assert app.build_command(
        "story", "现代情感：写一个完整故事", genre="03_现代情感",
        planner_mode="published",
    )[-2:] == ["--planner-mode", "published"]
    with pytest.raises(ValueError, match="未知规划方式"):
        app.build_command(
            "story", "现代情感：写一个完整故事", genre="03_现代情感",
            planner_mode="invalid",
        )


def test_route_request_uses_structured_llm_for_genre():
    calls = []

    def fake_llm(messages, schema):
        calls.append((messages, schema))
        return GenrePlan(genre="03_现代情感")

    plan = route_request("story", "情感类：民国时代银行家和天才画家的相爱故事", fake_llm)

    assert plan.genre == "03_现代情感"
    assert calls[0][1] is GenrePlan
    assert "json" in calls[0][0][0]["content"]
    assert "情感类" in calls[0][0][1]["content"]


def test_route_request_uses_selected_mode_without_llm_for_non_story():
    plan = route_request("evolve", "/tmp/story.txt", lambda *_: pytest.fail("不应调用 LLM"))
    assert plan == RoutePlan(action="evolve")


def test_route_request_rejects_unresolved_genre():
    with pytest.raises(ValueError, match="未识别题材"):
        route_request("story", "写一个故事", lambda *_: GenrePlan())


def test_validate_input_rejects_empty_missing_and_non_txt(tmp_path):
    with pytest.raises(ValueError, match="创作要求"):
        app.validate_input("story", " ")
    with pytest.raises(ValueError, match="不存在"):
        app.validate_input("bootstrap", tmp_path / "missing")
    non_txt = tmp_path / "story.md"
    non_txt.write_text("正文", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\.txt"):
        app.validate_input("evolve", non_txt)
    single_story = tmp_path / "single.txt"
    single_story.write_text("故事", encoding="utf-8")
    with pytest.raises(ValueError, match="Bootstrap 只能选择.*文件夹"):
        app.validate_input("bootstrap", single_story)


def test_run_process_forwards_merged_output_line_by_line():
    seen = []

    class FakeProcess:
        stdout = ["第一行\n", "第二行\r\n"]

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        assert command[0] == sys.executable
        assert "shell" not in kwargs
        assert kwargs["stderr"] is app.subprocess.STDOUT
        return FakeProcess()

    code, lines = app.run_process([sys.executable, "-V"], seen.append, fake_popen)

    assert code == 0
    assert lines == ["第一行", "第二行"]
    assert seen == lines


def test_worker_reads_manifest_and_emits_story_result(tmp_path, monkeypatch):
    story_path = tmp_path / "story.md"
    story_path.write_text("# 动态故事\n\n正文", encoding="utf-8")
    manifest_path = tmp_path / "pipeline_manifest.json"
    manifest_path.write_text(json.dumps({"story_markdown": str(story_path)}), encoding="utf-8")
    ui = app.StoryUI.__new__(app.StoryUI)
    ui.events = queue.Queue()
    monkeypatch.setattr(
        app, "route_request",
        lambda *_: RoutePlan(action="story", genre="02_古风仙侠"),
    )

    def fake_run_process(_command, on_line):
        line = f"[StoryCLI] pipeline_manifest={manifest_path}"
        on_line(line)
        return 0, [line]

    monkeypatch.setattr(app, "run_process", fake_run_process)
    ui._worker("story", "古风仙侠：正文")

    events = []
    while not ui.events.empty():
        events.append(ui.events.get_nowait())
    event = next(item for item in events if item[0] == "done")
    assert event[0:2] == ("done", True)
    assert "# 动态故事" in event[2]
    assert "正文文件：" in event[2]


def test_worker_reports_nonzero_process_and_keeps_error(monkeypatch):
    ui = app.StoryUI.__new__(app.StoryUI)
    ui.events = queue.Queue()
    monkeypatch.setattr(
        app, "route_request",
        lambda *_: RoutePlan(action="evolve"),
    )
    monkeypatch.setattr(app, "run_process", lambda *_args: (3, ["[StoryCLI] error: 失败原因"]))

    ui._worker("evolve", "/tmp/story.txt")

    events = []
    while not ui.events.empty():
        events.append(ui.events.get_nowait())
    assert next(event for event in events if event[0] == "done") == (
        "done", False, "任务失败，退出码=3",
    )


def test_worker_reports_missing_manifest_and_allows_ui_to_finish(monkeypatch):
    ui = app.StoryUI.__new__(app.StoryUI)
    ui.events = queue.Queue()
    monkeypatch.setattr(
        app, "route_request",
        lambda *_: RoutePlan(action="story", genre="01_悬疑惊悚"),
    )
    def fake_run_process(_command, on_line):
        line = "[StoryCLI] pipeline_manifest=/tmp/missing-manifest.json"
        on_line(line)
        return 0, [line]

    monkeypatch.setattr(app, "run_process", fake_run_process)

    ui._worker("story", "悬疑：正文")

    events = []
    while not ui.events.empty():
        events.append(ui.events.get_nowait())
    assert any(event[0] == "log" for event in events)
    done = next(event for event in events if event[0] == "done")
    assert done[0:2] == ("done", False)
    assert "pipeline_manifest 不存在" in done[2]


def test_worker_routes_before_starting_shell_free_cli(monkeypatch):
    ui = app.StoryUI.__new__(app.StoryUI)
    ui.events = queue.Queue()
    calls = []

    def fake_route(mode, value):
        calls.append(("route", mode, value))
        return RoutePlan(action="story", genre="03_现代情感")

    def fake_run_process(command, _on_line):
        calls.append(("run", command))
        return 0, []

    monkeypatch.setattr(app, "route_request", fake_route)
    monkeypatch.setattr(app, "run_process", fake_run_process)

    ui._worker("story", "情感类：民国故事")

    assert calls[0] == ("route", "story", "情感类：民国故事")
    assert calls[1][0] == "run"
    assert calls[1][1][-2:] == [
        "--planner-mode", "dynamic",
    ]
    request_index = calls[1][1].index("--request")
    assert calls[1][1][request_index + 1] == "现代情感：民国故事"


def test_worker_passes_selected_pattern_mode(monkeypatch):
    ui = app.StoryUI.__new__(app.StoryUI)
    ui.events = queue.Queue()
    commands = []
    monkeypatch.setattr(
        app, "route_request",
        lambda *_: RoutePlan(action="story", genre="03_现代情感"),
    )
    monkeypatch.setattr(
        app, "run_process",
        lambda command, _on_line: (commands.append(command) or 1, []),
    )

    ui._worker("story", "情感类：民国故事", planner_mode="published")

    assert commands[0][-2:] == ["--planner-mode", "published"]


def test_start_confirms_formal_reset_before_launching_worker(tmp_path, monkeypatch):
    source = tmp_path / "故事集"
    source.mkdir()
    (source / "故事1.txt").write_text("故事一", encoding="utf-8")
    (source / "故事2.txt").write_text("故事二", encoding="utf-8")

    class Value:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            started.append(self.args)

    started = []
    ui = app.StoryUI.__new__(app.StoryUI)
    ui.root = object()
    ui.mode = "bootstrap"
    ui.path = Value(source)
    ui.planner_mode = Value("dynamic")
    ui.reset_formal = Value(True)
    ui.log_text = object()
    ui.result_text = object()
    ui._set_running = lambda *_: None
    ui._set_text = lambda *_: None
    monkeypatch.setattr(app.messagebox, "askyesno", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(app.threading, "Thread", FakeThread)

    ui._start()

    assert started == [("bootstrap", str(source.resolve()), True, "dynamic")]


def test_finish_restores_controls_after_failure():
    class FakeButton:
        def __init__(self):
            self.states = []

        def config(self, **kwargs):
            self.states.append(kwargs["state"])

    class FakeText:
        def config(self, **_kwargs):
            pass

        def delete(self, *_args):
            pass

        def insert(self, *_args):
            pass

        def see(self, *_args):
            pass

    ui = app.StoryUI.__new__(app.StoryUI)
    ui.running = True
    ui.action_buttons = [FakeButton(), FakeButton()]
    ui.run_button = FakeButton()
    ui.result_text = FakeText()
    ui.log_text = FakeText()

    ui._finish(False, "任务失败")

    assert ui.running is False
    assert all(button.states[-1] == "normal" for button in ui.action_buttons + [ui.run_button])


def test_mode_switch_rebuilds_form_inside_fixed_container(monkeypatch):
    class FakeWidget:
        def __init__(self, parent=None, **_kwargs):
            self.parent = parent
            self.destroyed = False

        def pack(self, **_kwargs):
            pass

        def destroy(self):
            self.destroyed = True

        def get(self, *_args):
            assert not self.destroyed
            return ""

    monkeypatch.setattr(
        app, "ttk", SimpleNamespace(
            Frame=FakeWidget,
            LabelFrame=FakeWidget,
            Label=FakeWidget,
            Entry=FakeWidget,
            Button=FakeWidget,
            Checkbutton=FakeWidget,
            Radiobutton=FakeWidget,
        ),
    )
    monkeypatch.setattr(app, "ScrolledText", FakeWidget)
    ui = app.StoryUI.__new__(app.StoryUI)
    ui.mode = "bootstrap"
    ui.form = None
    ui.form_container = object()
    ui.path = object()
    ui.planner_mode = object()
    ui.reset_formal = object()
    ui.request_value = ""
    ui.request_text = None
    ui.running = False

    ui._build_form()
    forms = []
    for mode in ("story", "evolve", "bootstrap"):
        ui._select_mode(mode)
        forms.append(ui.form)

    assert all(form.parent is ui.form_container for form in forms)
    assert ui.mode == "bootstrap"
