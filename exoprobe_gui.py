#!/usr/bin/env python3
"""exoprobe GUI: a tkinter window over exoprobe.py.

Standard library only, like the tool it drives. The window runs the command line
tool as a subprocess with the same options it takes, so what it shows is what the
command line prints:

  Scan      lists every ExoPlayer cache under the folder, with its items, as a tree.
  Rejoin    writes every cache's joined media and a report.json into the output
            folder, then lists what was written. Double-click a file to open it.
  Mux       puts a video-only MP4 and one or more audio-only MP4s in one file.

The evidence folder is only read.

    python3 exoprobe_gui.py                   open the window
    python3 exoprobe_gui.py FOLDER            open it with the folder chosen
    python3 exoprobe_gui.py --cli ...         run the command line tool; this is how the
                                              window starts it, and what makes one
                                              frozen executable work
    python3 exoprobe_gui.py --smoke FOLDER OUTPUT
                                              no visible window: build it, rejoin
                                              through it, print what it listed, exit
"""

import json
import os
import queue
import runpy
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exoprobe  # noqa: E402  pylint: disable=wrong-import-position

TITLE = "exoprobe"


def probe_command():
    """How to start the command line tool as a subprocess (see run_cli)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--cli"]
    return [sys.executable, os.path.abspath(__file__), "--cli"]


def run_cli(argv):
    """Run exoprobe's command line with these arguments, in this process."""
    sys.argv = ["exoprobe.py"] + list(argv)
    try:
        runpy.run_module("exoprobe", run_name="__main__", alter_sys=False)
    except SystemExit as done:
        return done.code if isinstance(done.code, int) else (0 if done.code is None else 1)
    return 0


def open_path(path):
    """Open a file or folder with the system's default application."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # pylint: disable=no-member
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])  # pylint: disable=consider-using-with
    else:
        subprocess.Popen(["xdg-open", path])  # pylint: disable=consider-using-with


def written_files(folder):
    """(relative path, size) of every file under ``folder``, sorted."""
    result = []
    for base, _dirs, names in os.walk(folder):
        for name in names:
            path = os.path.join(base, name)
            result.append((os.path.relpath(path, folder).replace(os.sep, "/"), os.path.getsize(path)))
    return sorted(result)


def build_window(initial_folder="", smoke=None):
    """Build the window. With ``smoke`` = (folder, output) it rejoins once, hidden."""
    import tkinter as tk  # pylint: disable=import-outside-toplevel
    from tkinter import filedialog, messagebox, ttk  # pylint: disable=import-outside-toplevel

    root = tk.Tk()
    root.title(f"{TITLE} {exoprobe.__version__}")
    root.geometry("960x660")
    root.minsize(740, 500)
    if smoke:
        root.attributes("-alpha", 0.0)
    state = {"proc": None, "streams": 0, "mode": None, "result": None, "output": "", "cache": ""}
    lines = queue.Queue()

    form = ttk.Frame(root, padding=8)
    form.pack(fill="x")
    v_folder = tk.StringVar(value=initial_folder)
    v_output = tk.StringVar()
    v_combine = tk.BooleanVar(value=True)
    for row, (label, var, hint) in enumerate((
            ("Evidence folder", v_folder, "an extracted Android file system, or the part holding a cache"),
            ("Output folder", v_output, "for Rejoin; choose a new or empty folder"))):
        ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(form, textvariable=var).grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Button(form, text="Browse...",
                   command=lambda v=var, t=label: v.set(filedialog.askdirectory(title=t) or v.get())
                   ).grid(row=row, column=2, padx=(6, 0), pady=2)
        ttk.Label(form, text=hint, foreground="gray").grid(row=row, column=3, sticky="w", padx=(8, 0))
    ttk.Checkbutton(form, text="Put video and audio in one file", variable=v_combine
                    ).grid(row=2, column=1, sticky="w", pady=(2, 0))
    form.columnconfigure(1, weight=1)

    buttons = ttk.Frame(root, padding=(8, 0))
    buttons.pack(fill="x")
    b_scan = ttk.Button(buttons, text="Scan")
    b_rejoin = ttk.Button(buttons, text="Rejoin")
    b_mux = ttk.Button(buttons, text="Mux...")
    b_cancel = ttk.Button(buttons, text="Cancel", state="disabled")
    b_open = ttk.Button(buttons, text="Open output", state="disabled")
    actions = (b_scan, b_rejoin, b_mux)
    for button in actions + (b_cancel, b_open):
        button.pack(side="left", padx=(0, 6))

    status_bar = ttk.Frame(root, padding=(8, 6))
    status_bar.pack(fill="x")
    progress = ttk.Progressbar(status_bar, mode="indeterminate")
    progress.pack(side="left", fill="x", expand=True)
    status = ttk.Label(status_bar, text="Choose an evidence folder.", width=40)
    status.pack(side="left", padx=(8, 0))

    panes = ttk.PanedWindow(root, orient="vertical")
    panes.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    tree_frame = ttk.Frame(panes)
    tree = ttk.Treeview(tree_frame, columns=("detail",))
    tree.heading("#0", text="cache / item / file")
    tree.heading("detail", text="detail")
    tree.column("#0", width=420, stretch=True)
    tree.column("detail", width=440, stretch=True)
    scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="left", fill="y")
    log = tk.Text(panes, height=8, wrap="none", state="disabled")
    panes.add(tree_frame, weight=3)
    panes.add(log, weight=1)

    def write(text):
        log.configure(state="normal")
        log.insert("end", text)
        log.see("end")
        log.configure(state="disabled")

    def pump(stream, tag):
        for line in iter(stream.readline, b""):
            lines.put((tag, line.decode("utf-8", "replace").rstrip("\r\n")))
        lines.put((tag, None))

    def run(mode, args):
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")
        tree.delete(*tree.get_children())
        command = probe_command() + args
        shown = ["exoprobe.py"] + args
        write("$ " + " ".join(a if " " not in a else f'"{a}"' for a in shown) + "\n")
        state.update(mode=mode, cache="")
        status["text"] = "running..."
        progress.start(12)
        for button in actions + (b_open,):
            button["state"] = "disabled"
        b_cancel["state"] = "normal"
        try:
            state["proc"] = subprocess.Popen(  # pylint: disable=consider-using-with
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        except OSError as error:
            messagebox.showerror(TITLE, f"Could not start exoprobe: {error}")
            finish(None)
            return
        state["streams"] = 2
        threading.Thread(target=pump, args=(state["proc"].stdout, "out"), daemon=True).start()
        threading.Thread(target=pump, args=(state["proc"].stderr, "err"), daemon=True).start()
        root.after(50, poll)

    def folder_or_warn():
        folder = v_folder.get().strip()
        if not os.path.isdir(folder):
            messagebox.showinfo(TITLE, "Choose the evidence folder first.")
            return None
        return folder

    def scan():
        folder = folder_or_warn()
        if folder:
            run("scan", ["scan", folder])

    def rejoin():
        folder = folder_or_warn()
        if not folder:
            return
        output = v_output.get().strip()
        if not output:
            messagebox.showinfo(TITLE, "Choose an output folder first.")
            return
        if os.path.isdir(output) and os.listdir(output):
            messagebox.showerror(TITLE, f"Choose a new or empty output folder:\n{output}")
            return
        state["output"] = output
        run("rejoin", ["rejoin", folder, "-o", output] + ([] if v_combine.get() else ["--no-combine"]))

    def mux():
        video = filedialog.askopenfilename(title="Video-only MP4", filetypes=[("MP4", "*.mp4"), ("All", "*")])
        if not video:
            return
        audio = filedialog.askopenfilenames(title="Audio-only MP4 or M4A (one or more)",
                                            filetypes=[("Audio", "*.m4a *.mp4"), ("All", "*")])
        if not audio:
            return
        output = filedialog.asksaveasfilename(title="Combined file", defaultextension=".mp4",
                                              filetypes=[("MP4", "*.mp4")])
        if not output:
            return
        if os.path.exists(output):
            messagebox.showerror(TITLE, f"Refusing to overwrite an existing file:\n{output}")
            return
        state["output"] = os.path.dirname(output)
        run("mux", ["mux", video, *audio, "-o", output])

    def on_line(tag, line):
        if tag == "out" and state["mode"] == "scan" and line:
            if not line.startswith(" "):
                name, _, detail = line.partition("  (")
                state["cache"] = tree.insert("", "end", text=name, values=("(" + detail,), open=False)
            elif state["cache"]:
                number, _, detail = line.strip().partition(": ")
                tree.insert(state["cache"], "end", text=number, values=(detail,))
            return
        if line.strip():
            write(line + "\n")

    def poll():
        try:
            while True:
                tag, line = lines.get_nowait()
                if line is None:
                    state["streams"] -= 1
                else:
                    on_line(tag, line)
        except queue.Empty:
            pass
        proc = state["proc"]
        if proc is not None and (proc.poll() is None or state["streams"] > 0):
            root.after(50, poll)
            return
        finish(proc.returncode if proc is not None else None)

    def finish(code):
        progress.stop()
        for button in actions:
            button["state"] = "normal"
        b_cancel["state"] = "disabled"
        state["proc"] = None
        count = 0
        if code == 0 and state["mode"] == "rejoin":
            for relative, size in written_files(state["output"]):
                tree.insert("", "end", text=relative, values=(f"{size:,} bytes",))
                count += 1
            b_open["state"] = "normal"
        elif code == 0 and state["mode"] == "mux":
            b_open["state"] = "normal"
        if code == 0:
            noun = {"scan": f"{len(tree.get_children()):,} caches", "rejoin": f"{count:,} files written",
                    "mux": "combined file written"}.get(state["mode"], "")
            status["text"] = f"done: {noun}"
        elif code is None:
            status["text"] = "not started"
        elif code < 0:
            status["text"] = "cancelled"
        else:
            status["text"] = f"exoprobe exited {code}"
        state["result"] = (code, count)
        if smoke:
            root.after(10, root.destroy)

    def cancel():
        proc = state["proc"]
        if proc is not None and proc.poll() is None:
            proc.terminate()
            write("\n[cancelled: the output holds only what was written before the cancel]\n")

    def open_selected(_event=None):
        selection = tree.selection()
        if state["mode"] != "rejoin" or not selection or tree.parent(selection[0]):
            return
        open_path(os.path.join(state["output"], tree.item(selection[0], "text")))

    b_scan.configure(command=scan)
    b_rejoin.configure(command=rejoin)
    b_mux.configure(command=mux)
    b_cancel.configure(command=cancel)
    b_open.configure(command=lambda: state["output"] and open_path(state["output"]))
    tree.bind("<Double-1>", open_selected)

    def on_close():
        cancel()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    if smoke:
        v_folder.set(smoke[0])
        v_output.set(smoke[1])
        root.after(100, rejoin)
    root.mainloop()
    return state["result"]


def main(argv):
    if argv and argv[0] == "--cli":
        return run_cli(argv[1:])
    if argv and argv[0] == "--smoke":
        if len(argv) != 3:
            print("usage: exoprobe_gui.py --smoke FOLDER OUTPUT", file=sys.stderr)
            return 2
        code, files = build_window(smoke=(os.path.abspath(argv[1]), os.path.abspath(argv[2]))) or (None, 0)
        print(json.dumps({"exit": code, "files": files}))
        return 0 if code == 0 else 1
    build_window(os.path.abspath(argv[0]) if argv and os.path.isdir(argv[0]) else "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
