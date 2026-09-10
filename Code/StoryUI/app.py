"""Tkinter 交互窗口：先由 LLM 路由，再调用公开 StoryCLI 命令。"""

import json
import queue
import re
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from StoryUI.router import GENRE_ALIASES, GENRES, route_request


ROOT = Path(__file__).resolve().parent.parent
MODES = {
    "bootstrap": "1. Bootstrap",
    "evolve": "2. Evolve",
    "story": "3. 生成文章",
}
PIPELINE_MANIFEST = re.compile(r"^\[StoryCLI\] pipeline_manifest=(.+)$")


def normalize_story_request(value, genre):
    label = genre.split("_", 1)[1]
    aliases = "|".join(
        re.escape(alias) for alias in sorted(GENRE_ALIASES[genre], key=len, reverse=True)
    )
    value = re.sub(rf"^(?:(?:{aliases})\s*[:：]\s*)+", "", value)
    return f"{label}：{value}"


def build_command(mode, value, reset_formal=False, genre=None, planner_mode="dynamic"):
    """Build a shell-free command for one public StoryCLI operation."""
    if mode not in MODES:
        raise ValueError(f"未知操作: {mode}")
    value = str(value).strip()
    if not value:
        raise ValueError("请输入路径或创作要求")
    command = [sys.executable, "-u", "-X", "utf8", "-m", "StoryCLI"]
    if mode == "bootstrap":
        command += ["bootstrap", "--input", value]
        if reset_formal:
            command.append("--reset-formal")
    elif mode == "evolve":
        command += ["evolve", "--input", value, "--promote"]
    else:
        if genre not in GENRES:
            raise ValueError("生成文章需要 LLM 识别出一个有效题材")
        if planner_mode not in ("dynamic", "published"):
            raise ValueError(f"未知规划方式: {planner_mode}")
        value = normalize_story_request(value, genre)
        command += [
            "story", "generate", "--request", value,
            "--planner-mode", planner_mode,
        ]
    return command


def validate_input(mode, value):
    value = str(value).strip()
    if mode == "story":
        if not value:
            raise ValueError("请输入创作要求")
        return value
    if not value:
        raise ValueError("请输入 Bootstrap 或 Evolve 的文件/文件夹路径")
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"输入路径不存在: {path}")
    if mode == "bootstrap" and path.is_file():
        raise ValueError("Bootstrap 只能选择包含至少 2 个 .txt 故事的文件夹；单篇故事请使用 Evolve")
    if path.is_file() and path.suffix.lower() != ".txt":
        raise ValueError("输入文件必须是 .txt")
    return str(path)


def run_process(command, on_line, popen_factory=subprocess.Popen):
    """Run one command and forward merged stdout/stderr line by line."""
    process = popen_factory(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines = []
    for line in process.stdout:
        line = line.rstrip("\r\n")
        lines.append(line)
        on_line(line)
    return process.wait(), lines


def find_pipeline_manifest(lines):
    for line in reversed(lines):
        match = PIPELINE_MANIFEST.match(line.strip())
        if match:
            path = Path(match.group(1).strip()).expanduser().resolve()
            if not path.is_file():
                raise ValueError(f"pipeline_manifest 不存在: {path}")
            return path
    raise ValueError("生成流程没有返回 pipeline_manifest")


def load_story_markdown(manifest_path):
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 pipeline_manifest: {manifest_path}") from exc
    story_value = manifest.get("story_markdown")
    if not story_value:
        raise ValueError("pipeline_manifest 缺少 story_markdown")
    story_path = Path(story_value).expanduser().resolve()
    try:
        return story_path, story_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取正文文件: {story_path}") from exc


class StoryUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Function Extraction")
        self.root.geometry("1000x760")
        self.root.minsize(760, 560)
        self.mode = "bootstrap"
        self.path = tk.StringVar()
        self.planner_mode = tk.StringVar(value="dynamic")
        self.reset_formal = tk.BooleanVar(value=False)
        self.events = queue.Queue()
        self.running = False
        self.request_value = ""
        self.request_text = None
        self.form = None
        self.action_buttons = []

        self._build_header()
        self.form_container = ttk.Frame(self.root)
        self.form_container.pack(fill="x", padx=16, pady=(0, 12))
        self._build_form()
        self._build_output()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(100, self._poll_events)

    def _build_header(self):
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="x")
        ttk.Label(
            frame, text="Function Extraction", font=("TkDefaultFont", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(frame, text="请选择操作；生成文章时先由 LLM 识别题材，再调用固定的 StoryCLI 流程").pack(
            anchor="w", pady=(4, 12),
        )
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        for mode, label in MODES.items():
            button = ttk.Button(buttons, text=label, command=lambda value=mode: self._select_mode(value))
            button.pack(side="left", padx=(0, 8))
            self.action_buttons.append(button)

    def _build_form(self):
        if self.form is not None:
            if self.request_text is not None:
                self.request_value = self.request_text.get("1.0", "end").strip()
                self.request_text = None
            self.form.destroy()
        self.form = ttk.LabelFrame(self.form_container, text=MODES[self.mode], padding=12)
        self.form.pack(fill="x")
        if self.mode == "story":
            ttk.Label(self.form, text="创作要求（LLM 会先识别题材，可直接输入‘情感类：……’）").pack(anchor="w")
            self.request_text = ScrolledText(self.form, height=7, wrap="word")
            self.request_text.pack(fill="x", pady=(6, 0))
            if self.request_value:
                self.request_text.insert("1.0", self.request_value)
            planner_row = ttk.Frame(self.form)
            planner_row.pack(fill="x", pady=(8, 0))
            ttk.Label(planner_row, text="规划方式：").pack(side="left")
            ttk.Radiobutton(
                planner_row, text="Dynamic（动态组合 Function）",
                variable=self.planner_mode, value="dynamic",
            ).pack(side="left", padx=(4, 12))
            ttk.Radiobutton(
                planner_row, text="Pattern（使用已发布结构）",
                variable=self.planner_mode, value="published",
            ).pack(side="left")
        else:
            label = (
                "Bootstrap 故事文件夹路径（至少包含 2 个 .txt，递归收集）"
                if self.mode == "bootstrap"
                else "新故事文件或文件夹路径（文件必须是 .txt）"
            )
            ttk.Label(self.form, text=label).pack(anchor="w")
            path_row = ttk.Frame(self.form)
            path_row.pack(fill="x", pady=(6, 0))
            ttk.Entry(path_row, textvariable=self.path).pack(side="left", fill="x", expand=True)
            if self.mode == "evolve":
                ttk.Button(path_row, text="选择文件", command=self._choose_file).pack(side="left", padx=(8, 0))
            ttk.Button(path_row, text="选择文件夹", command=self._choose_folder).pack(side="left", padx=(8, 0))
            if self.mode == "bootstrap":
                ttk.Checkbutton(
                    self.form,
                    text="归档并重建正式库（执行前还会再次确认）",
                    variable=self.reset_formal,
                ).pack(anchor="w", pady=(8, 0))
        button_text = "生成文章" if self.mode == "story" else "开始执行"
        self.run_button = ttk.Button(self.form, text=button_text, command=self._start)
        self.run_button.pack(anchor="e", pady=(10, 0))

    def _build_output(self):
        output = ttk.Panedwindow(self.root, orient="vertical")
        output.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        log_frame = ttk.Labelframe(output, text="运行日志", padding=6)
        self.log_text = ScrolledText(log_frame, height=12, wrap="none", state="disabled")
        self.log_text.pack(fill="both", expand=True)
        result_frame = ttk.Labelframe(output, text="结果 / 正文", padding=6)
        self.result_text = ScrolledText(result_frame, height=14, wrap="word", state="disabled")
        self.result_text.pack(fill="both", expand=True)
        output.add(log_frame, weight=1)
        output.add(result_frame, weight=2)

    def _select_mode(self, mode):
        if not self.running and mode != self.mode:
            self.mode = mode
            self._build_form()

    def _choose_file(self):
        path = filedialog.askopenfilename(
            title="选择 TXT 故事文件", filetypes=(("TXT 文件", "*.txt"),),
        )
        if path:
            self.path.set(path)

    def _choose_folder(self):
        path = filedialog.askdirectory(title="选择故事文件夹")
        if path:
            self.path.set(path)

    def _start(self):
        try:
            value = self.request_text.get("1.0", "end").strip() if self.mode == "story" else self.path.get()
            value = validate_input(self.mode, value)
            if self.mode == "bootstrap" and self.reset_formal.get():
                confirmed = messagebox.askyesno(
                    "确认重建正式库",
                    "这会先归档并重建正式 Knowledge DB、Registry、Bank 和 checkpoint。确定继续吗？",
                    parent=self.root,
                )
                if not confirmed:
                    return
        except ValueError as exc:
            messagebox.showerror("输入有误", str(exc), parent=self.root)
            return
        reset_formal = self.reset_formal.get()
        planner_mode = self.planner_mode.get() if self.mode == "story" else "dynamic"
        self._set_running(True)
        self._set_text(
            self.log_text,
            ("正在请求 LLM 识别题材……" if self.mode == "story" else "准备执行已选择的操作……")
            + "\n\n",
        )
        self._set_text(self.result_text, "")
        threading.Thread(
            target=self._worker,
            args=(self.mode, value, reset_formal, planner_mode),
            daemon=True,
        ).start()

    def _worker(self, mode, value, reset_formal=False, planner_mode="dynamic"):
        lines = []
        try:
            plan = route_request(mode, value)
            route_text = f"已选择操作：{plan.action}"
            if plan.genre:
                route_text += f"；LLM 识别题材：{plan.genre}"
            self.events.put(("log", route_text))
            command = build_command(
                mode, value, reset_formal, plan.genre, planner_mode,
            )
            self.events.put(("log", "执行命令：" + shlex.join(command)))
            code, lines = run_process(command, lambda line: self.events.put(("log", line)))
            if code:
                raise RuntimeError(f"任务失败，退出码={code}")
            result = "\n".join(
                line for line in lines
                if any(key in line for key in ("function_run=", "candidate_snapshot=", "serving_snapshot=", "pipeline_manifest="))
            )
            if mode == "story":
                manifest_path = find_pipeline_manifest(lines)
                story_path, story = load_story_markdown(manifest_path)
                result = f"正文文件：{story_path}\n\n{story}"
            self.events.put(("done", True, result))
        except Exception as exc:
            self.events.put(("done", False, str(exc)))

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "log":
                    self._append_text(self.log_text, event[1] + "\n")
                else:
                    self._finish(event[1], event[2])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _finish(self, success, result):
        self._set_running(False)
        self._set_text(self.result_text, result)
        self._append_text(self.log_text, ("\n任务完成\n" if success else f"\n任务失败：{result}\n"))

    def _set_running(self, running):
        self.running = running
        state = "disabled" if running else "normal"
        for button in self.action_buttons:
            button.config(state=state)
        self.run_button.config(state=state)

    @staticmethod
    def _set_text(widget, value):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.config(state="disabled")

    @staticmethod
    def _append_text(widget, value):
        widget.config(state="normal")
        widget.insert("end", value)
        widget.see("end")
        widget.config(state="disabled")

    def _close(self):
        if self.running:
            messagebox.showinfo("任务运行中", "当前任务仍在运行，请等待任务完成后再关闭窗口。", parent=self.root)
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    StoryUI(root)
    root.mainloop()
