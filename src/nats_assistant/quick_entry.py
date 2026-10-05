from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence
from urllib import error, request

try:
    import tkinter as tk
    from tkinter import messagebox
except ImportError:  # pragma: no cover - tkinter is the intended local GUI toolkit on Debian/Kali.
    tk = None
    messagebox = None

BASE_URL = "http://127.0.0.1:8765/v1"


def normalize_argv(argv: Sequence[str] | None = None) -> list[str]:
    tokens = list(argv if argv is not None else sys.argv[1:])
    if not tokens:
        return tokens

    if tokens[0] in {"quick-task", "quick-capture", "quick-add-task"}:
        mapped = tokens[0].replace("quick-", "").replace("add-", "")
        return ["quick", mapped, *tokens[1:]]
    if tokens[0] in {"task", "capture"}:
        return ["quick", tokens[0], *tokens[1:]]
    return tokens


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    normalized = normalize_argv(argv)
    parser = argparse.ArgumentParser(prog="nats-assistant")
    subparsers = parser.add_subparsers(dest="command")
    quick_parser = subparsers.add_parser("quick", help="Open a quick task or capture dialog")
    quick_parser.add_argument(
        "mode",
        choices=["task", "capture", "add-task", "quick-task", "quick-capture"],
        help="The type of quick entry to launch",
    )
    quick_parser.add_argument("--title", default="", help="Task title")
    quick_parser.add_argument("--priority", choices=["low", "normal", "high", "critical"], default="normal")
    quick_parser.add_argument("--text", default="", help="Capture text")
    args = parser.parse_args(normalized)
    if args.command == "quick" and args.mode in {"add-task", "quick-task"}:
        args.mode = "task"
    if args.command == "quick" and args.mode in {"quick-capture"}:
        args.mode = "capture"
    return args


def build_task_payload(values: dict[str, Any] | None = None) -> dict[str, Any]:
    source = values or {}
    title = str(source.get("title", "")).strip()
    if not title:
        raise ValueError("Task title is required")
    priority = str(source.get("priority", "normal")).strip().lower()
    payload = {"title": title, "priority": priority}
    if source.get("description") is not None:
        payload["description"] = str(source["description"]).strip() or None
    if source.get("due") not in (None, ""):
        payload["due"] = source["due"]
    return payload


def build_capture_payload(values: dict[str, Any] | None = None) -> dict[str, Any]:
    source = values or {}
    text = str(source.get("text", "")).strip()
    if not text:
        raise ValueError("Capture text is required")
    payload = {"text": text}
    if source.get("source"):
        payload["source"] = str(source["source"]).strip()
    return payload


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | list[dict[str, Any]] | None:
    request_body = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        request_body = json.dumps(payload).encode("utf-8")
    req = request.Request(f"{BASE_URL}{path}", data=request_body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=5) as response:
            body = response.read().decode("utf-8")
            if not body:
                return None
            return json.loads(body)
    except error.URLError as exc:
        raise RuntimeError("NATS Assistant is offline") from exc
    except error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8")
            payload_json = json.loads(error_body) if error_body else {}
            detail = payload_json.get("detail", str(exc))
        except Exception:
            detail = str(exc)
        raise RuntimeError(detail) from exc


def submit_task(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/tasks", build_task_payload(payload))


def submit_capture(payload: dict[str, Any]) -> dict[str, Any]:
    return request_json("POST", "/captures", build_capture_payload(payload))


def _show_error(title: str, message: str, parent: Any | None = None) -> None:
    if messagebox is None:
        print(f"{title}: {message}")
        return
    if parent is None:
        messagebox.showerror(title, message)
    else:
        messagebox.showerror(title, message, parent=parent)


class TaskQuickEntryDialog:
    def __init__(self, initial_title: str = "", initial_priority: str = "normal"):
        self.root = tk.Tk()
        self.root.withdraw()
        self.dialog = tk.Toplevel(self.root)
        self.dialog.title("Quick task")
        self.dialog.resizable(False, False)
        self.title_var = tk.StringVar(value=initial_title)
        self.priority_var = tk.StringVar(value=initial_priority if initial_priority in {"low", "normal", "high", "critical"} else "normal")

        tk.Label(self.dialog, text="Title").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        title_entry = tk.Entry(self.dialog, textvariable=self.title_var, width=36)
        title_entry.grid(row=0, column=1, padx=10, pady=(10, 2), sticky="ew")
        title_entry.focus_set()

        tk.Label(self.dialog, text="Priority").grid(row=1, column=0, sticky="w", padx=10, pady=2)
        options = ["low", "normal", "high", "critical"]
        menu = tk.OptionMenu(self.dialog, self.priority_var, *options)
        menu.grid(row=1, column=1, padx=10, pady=2, sticky="ew")
        self.priority_var.set(self.priority_var.get() if self.priority_var.get() in options else "normal")

        buttons = tk.Frame(self.dialog)
        buttons.grid(row=2, column=0, columnspan=2, pady=(10, 12), padx=10, sticky="e")
        cancel_btn = tk.Button(buttons, text="Cancel", command=self.close)
        cancel_btn.grid(row=0, column=0, padx=(0, 6))
        save_btn = tk.Button(buttons, text="Add", command=self.save)
        save_btn.grid(row=0, column=1)

        self.dialog.bind("<Return>", lambda _event: self.save())
        self.dialog.bind("<Escape>", lambda _event: self.close())

    def save(self) -> None:
        try:
            payload = build_task_payload({
                "title": self.title_var.get(),
                "priority": self.priority_var.get(),
            })
            submit_task(payload)
            self.close()
        except RuntimeError as exc:
            _show_error("NATS Assistant is offline", str(exc), parent=self.dialog)
        except ValueError as exc:
            _show_error("Task validation", str(exc), parent=self.dialog)

    def close(self) -> None:
        self.dialog.destroy()
        self.root.destroy()


def open_task_quick_entry(title: str = "", priority: str = "normal") -> None:
    if tk is None:
        raise RuntimeError("tkinter is not available")
    dialog = TaskQuickEntryDialog(initial_title=title, initial_priority=priority)
    dialog.dialog.mainloop()


class CaptureQuickEntryDialog:
    def __init__(self, initial_text: str = ""):
        self.root = tk.Tk()
        self.root.withdraw()
        self.dialog = tk.Toplevel(self.root)
        self.dialog.title("Quick capture")
        self.dialog.resizable(False, False)
        self.text_var = tk.StringVar(value=initial_text)

        tk.Label(self.dialog, text="Capture").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        text_entry = tk.Entry(self.dialog, textvariable=self.text_var, width=44)
        text_entry.grid(row=0, column=1, padx=10, pady=(10, 2), sticky="ew")
        text_entry.focus_set()

        buttons = tk.Frame(self.dialog)
        buttons.grid(row=1, column=0, columnspan=2, pady=(10, 12), padx=10, sticky="e")
        cancel_btn = tk.Button(buttons, text="Cancel", command=self.close)
        cancel_btn.grid(row=0, column=0, padx=(0, 6))
        save_btn = tk.Button(buttons, text="Save", command=self.save)
        save_btn.grid(row=0, column=1)

        self.dialog.bind("<Return>", lambda _event: self.save())
        self.dialog.bind("<Escape>", lambda _event: self.close())

    def save(self) -> None:
        try:
            payload = build_capture_payload({"text": self.text_var.get()})
            submit_capture(payload)
            self.close()
        except RuntimeError as exc:
            _show_error("NATS Assistant is offline", str(exc), parent=self.dialog)
        except ValueError as exc:
            _show_error("Capture validation", str(exc), parent=self.dialog)

    def close(self) -> None:
        self.dialog.destroy()
        self.root.destroy()


def open_capture_quick_entry(text: str = "") -> None:
    if tk is None:
        raise RuntimeError("tkinter is not available")
    dialog = CaptureQuickEntryDialog(initial_text=text)
    dialog.dialog.mainloop()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command != "quick":
        raise SystemExit("Use: nats-assistant quick task | nats-assistant quick capture")

    if args.mode in {"task", "add-task", "quick-task"}:
        open_task_quick_entry()
        return 0
    if args.mode in {"capture", "quick-capture"}:
        open_capture_quick_entry()
        return 0

    raise SystemExit(f"Unsupported quick mode: {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
