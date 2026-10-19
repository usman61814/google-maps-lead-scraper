"""Simple Tkinter UI for the Google Maps lead scraper. Run: python app.py"""
import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

import maps_stealth_scraper as scraper

FILTER_OPTIONS = {"Any": None, "Has it": "has", "Missing": "missing"}


class QueueHandler(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(self.format(record))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Maps Lead Scraper")
        self.geometry("820x620")
        self.logs = queue.Queue()
        self.worker = None

        handler = QueueHandler(self.logs)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        scraper.log.addHandler(handler)

        tk.Label(self, text="Search keywords (one per line, e.g. 'pet care services in Multan'):").pack(anchor="w", padx=10, pady=(10, 0))
        self.keywords = tk.Text(self, height=5)
        self.keywords.pack(fill="x", padx=10)

        row = tk.Frame(self)
        row.pack(fill="x", padx=10, pady=8)
        tk.Label(row, text="Leads per keyword:").pack(side="left")
        self.count = tk.Spinbox(row, from_=1, to=500, width=5)
        self.count.delete(0, "end")
        self.count.insert(0, "20")
        self.count.pack(side="left", padx=(4, 16))
        tk.Label(row, text="Output file:").pack(side="left")
        self.output = tk.Entry(row, width=24)
        self.output.insert(0, "leads.csv")
        self.output.pack(side="left", padx=4)
        self.headless = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="Hide browser (no CAPTCHA help)", variable=self.headless).pack(side="left", padx=12)

        fields_row = tk.Frame(self)
        fields_row.pack(fill="x", padx=10)
        tk.Label(fields_row, text="Fields to save:  Business Name +").pack(side="left")
        self.fields = {}
        for col in scraper.COLUMNS[1:]:
            self.fields[col] = tk.BooleanVar(value=True)
            tk.Checkbutton(fields_row, text=col, variable=self.fields[col]).pack(side="left")

        filter_row = tk.Frame(self)
        filter_row.pack(fill="x", padx=10, pady=8)
        tk.Label(filter_row, text="Only keep leads where:").pack(side="left")
        self.filters = {}
        for col, label in [("Website Link", "Website"), ("Phone Number", "Phone")]:
            tk.Label(filter_row, text=f"  {label}").pack(side="left")
            self.filters[col] = tk.StringVar(value="Any")
            tk.OptionMenu(filter_row, self.filters[col], *FILTER_OPTIONS).pack(side="left")

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10)
        self.start_btn = tk.Button(btns, text="Start", width=10, command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = tk.Button(btns, text="Stop", width=10, command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        tk.Button(btns, text="Open results folder", command=self.open_folder).pack(side="left")
        self.status = tk.Label(btns, text="Idle", fg="gray")
        self.status.pack(side="right")

        self.logbox = scrolledtext.ScrolledText(self, state="disabled", height=18)
        self.logbox.pack(fill="both", expand=True, padx=10, pady=10)

        self.after(200, self.pump_logs)

    def start(self):
        queries = [l.strip() for l in self.keywords.get("1.0", "end").splitlines() if l.strip()]
        if not queries:
            messagebox.showwarning("Missing keywords", "Enter at least one search keyword.")
            return
        try:
            count = int(self.count.get())
        except ValueError:
            messagebox.showwarning("Invalid number", "Leads per keyword must be a number.")
            return
        name = self.output.get().strip() or "leads.csv"
        if not name.lower().endswith(".csv"):
            name += ".csv"
        fields = ["Business Name"] + [c for c, v in self.fields.items() if v.get()]
        filters = {c: FILTER_OPTIONS[v.get()] for c, v in self.filters.items() if FILTER_OPTIONS[v.get()]}

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status.config(text="Running...", fg="green")
        self.worker = threading.Thread(
            target=self.run_job, args=(queries, count, name, self.headless.get(), fields, filters), daemon=True
        )
        self.worker.start()

    def run_job(self, queries, count, name, headless, fields, filters):
        try:
            scraper.scrape(queries, count, name, headless, fields, filters)
        except Exception as exc:
            self.logs.put(f"ERROR: {exc}")
        self.logs.put("__DONE__")

    def stop(self):
        scraper.STOP.set()
        self.status.config(text="Stopping...", fg="orange")

    def open_folder(self):
        scraper.OUTPUT_DIR.mkdir(exist_ok=True)
        os.startfile(scraper.OUTPUT_DIR.resolve())

    def pump_logs(self):
        while not self.logs.empty():
            line = self.logs.get()
            if line == "__DONE__":
                self.start_btn.config(state="normal")
                self.stop_btn.config(state="disabled")
                self.status.config(text="Idle", fg="gray")
                continue
            self.logbox.config(state="normal")
            self.logbox.insert("end", line + "\n")
            self.logbox.see("end")
            self.logbox.config(state="disabled")
        self.after(200, self.pump_logs)


if __name__ == "__main__":
    App().mainloop()
