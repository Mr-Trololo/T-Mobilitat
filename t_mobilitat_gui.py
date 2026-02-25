#!/usr/bin/env python3
"""T-Mobilitat Card Viewer — v3"""
import json, math, time
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

# ─── Palette ──────────────────────────────────────────────────────────────────
BG = "#0c0e14"
BG_NAV = "#12151e"
BG_CARD = "#161924"
BG_RAISED = "#1c2030"
BG_HOVER = "#242939"

FG = "#e2e4eb"
FG2 = "#c4c7d4"
FG_DIM = "#6b7194"
FG_MUTED = "#4a5070"
ACCENT = "#5b9cf6"
ACCENT2 = "#9b7af6"
GREEN = "#3dd9a0"
YELLOW = "#f5c842"
ORANGE = "#f59e42"
RED = "#f06060"
LIME = "#a8e040"
BORDER = "#252a3a"
GLOW = "#3b82f6"

_FM = "Segoe UI"
_FC = "Consolas"
F_CARD = (_FC, 24, "bold")
F_SECTION = (_FM, 14, "bold")
F_SUB = (_FM, 12, "bold")
F_BODY = (_FM, 11)
F_SM = (_FM, 10)
F_SM_B = (_FM, 10, "bold")
F_XS = (_FM, 9)
F_XS_B = (_FM, 9, "bold")
F_MONO = (_FC, 10)
F_BIG = (_FM, 32, "bold")
F_NAV = (_FM, 10)
F_NAV_A = (_FM, 10, "bold")

# ─── Pass DB ─────────────────────────────────────────────────────────────────
PASS_DB = {
    "T-casual": {"trip_total": 10, "cat": "trip"},
    "T-familiar": {"trip_total": 8, "cat": "trip"},
    "T-grup": {"trip_total": 70, "cat": "trip"},
    "T-usual": {"dur": 30, "cat": "time"},
    "T-jove": {"dur": 90, "cat": "time"},
    "T-dia": {"dur": 1, "cat": "time"},
    "T-70/30": {"trip_total": 70, "dur": 30, "cat": "hybrid"},
    "T-70/90": {"trip_total": 70, "dur": 90, "cat": "hybrid"},
}
MAG_DB = {440: "T-jove", 400: "T-casual", 410: "T-usual", 420: "T-familiar"}


# ─── Helpers ──────────────────────────────────────────────────────────────────
def pretty(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False)


def ctrl_chars(n):
    t = "TRWAGMYFPDXBNJZSQVHLCKE"
    r = n % 23
    q = n // 23
    f = (q + r + 1) % 23
    d = f"{n:09d}"
    return f"{d[:3]} {d[3:6]} {d[6:]}{t[f]}{t[r]}"


def pdate(s):
    if not s:
        return None
    for f in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f)
        except:
            pass
    return None


def lerp(c1, c2, t):
    t = max(0, min(1, t))
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return f"#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}"


def id_pass(inst):
    name = (inst.get("name") or "").strip()
    mag = inst.get("magnetic_code")
    for k in PASS_DB:
        if k.lower() == name.lower():
            return k, PASS_DB[k]
    if mag and mag in MAG_DB:
        r = MAG_DB[mag]
        if r in PASS_DB:
            return r, PASS_DB[r]
    return name or "Unknown", None


def progress_info(inst, db):
    if not db:
        return None, "", ""
    cat = db.get("cat", "trip")
    loads = inst.get("loads", [])
    al = None
    for l in loads:
        if l.get("is_the_active_load"):
            al = l
            break
    if not al:
        for l in loads:
            if l.get("is_valid") and not l.get("is_expired"):
                al = l
                break
    if not al and loads:
        al = loads[0]
    if not al:
        return None, "", ""
    if cat == "trip":
        tot = db.get("trip_total", 10)
        rem = al.get("trip_balance", 0)
        return (
            (rem / tot if tot else 0),
            f"{rem}/{tot} trips",
            f"{rem} of {tot} trips remaining",
        )
    elif cat == "time":
        ini, end = pdate(al.get("init_date")), pdate(al.get("end_date"))
        if not ini or not end:
            return None, "", ""
        now = datetime.now()
        td = (end - ini).days
        if td <= 0:
            return 0, "Expired", ""
        rd = max(0, (end - now).days)
        if now > end:
            return 0, "Expired", f"Expired {abs(rd)} days ago"
        return rd / td, f"{rd}d left", f"{rd} of {td} days remaining"
    elif cat == "hybrid":
        tot = db.get("trip_total", 70)
        rem = al.get("trip_balance", 0)
        tp = rem / tot if tot else 0
        ini, end = pdate(al.get("init_date")), pdate(al.get("end_date"))
        tpp = 1.0
        tl = ""
        if ini and end:
            now = datetime.now()
            td = (end - ini).days
            rd = max(0, (end - now).days)
            tpp = rd / td if td else 0
            tl = f" · {rd}d left"
        return min(tp, tpp), f"{rem}/{tot} trips{tl}", ""
    return None, "", ""


def detect_swaps(loads):
    s = sorted(loads, key=lambda l: l.get("sale_datetime", ""))
    out = []
    for i in range(1, len(s)):
        pe = pdate(s[i - 1].get("end_date"))
        cs = pdate(s[i].get("sale_datetime") or s[i].get("init_date"))
        if pe and cs and cs < pe:
            out.append((s[i - 1], s[i]))
    return out


def bar_color(p):
    if p <= 0.05:
        return RED
    if p <= 0.10:
        return ORANGE
    if p <= 0.20:
        return YELLOW
    if p <= 0.50:
        return LIME
    return GREEN


# ─── Animated progress bar ───────────────────────────────────────────────────
class ProgressBar(tk.Canvas):
    def __init__(self, master, target=0.5, w=420, h=24, label="", radius=5, **kw):
        super().__init__(
            master, width=w, height=h, bg=BG_CARD, highlightthickness=0, **kw
        )
        self.W, self.H, self.R = w, h, radius
        self.target = max(0, min(1, target))
        self.cur = 0.0
        self.label = label
        self.t0 = None
        self._draw(0)
        self.after(60, self._go)

    def _go(self):
        self.t0 = time.time()
        self._tick()

    def _tick(self):
        t = min(1.0, (time.time() - self.t0) / 1.0)
        ease = 1 - (1 - t) ** 4
        self.cur = self.target * ease
        self._draw(self.cur)
        if t < 1.0:
            self.after(12, self._tick)

    def _rrect(self, x1, y1, x2, y2, r, **kw):
        pts = [
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
        ]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self, pct):
        self.delete("all")
        p = 1
        bw = self.W - 2
        bh = self.H - 2
        self._rrect(
            p,
            p,
            p + bw,
            p + bh,
            self.R,
            fill=lerp(bar_color(self.target), BG_CARD, 0.82),
            outline="",
        )
        fw = max(self.R * 2, bw * pct) if pct > 0.01 else 0
        if fw > 0:
            c = bar_color(self.target)
            self._rrect(p, p, p + fw, p + bh, self.R, fill=c, outline="")
            if fw > 8:
                self.create_line(
                    p + self.R,
                    p + 2,
                    p + fw - self.R,
                    p + 2,
                    fill=lerp(c, "#ffffff", 0.25),
                    width=1,
                )
        if self.label:
            self.create_text(
                p + bw / 2,
                p + bh / 2,
                text=self.label,
                fill="#e8e8f0",
                font=F_XS_B,
                anchor="center",
            )


# ─── Nav button (icon + optional label) ──────────────────────────────────────
class NavBtn(tk.Canvas):
    INTERVAL = 16

    def __init__(self, master, text, icon, command, **kw):
        super().__init__(
            master, height=36, bg=BG_NAV, highlightthickness=0, cursor="hand2", **kw
        )
        self.cmd = command
        self.text = text
        self.icon = icon
        self.active = False
        self._hp = 0.0
        self._ht = 0.0
        self._running = False
        self.show_label = True
        self.bind("<Enter>", lambda e: self._target(1.0))
        self.bind("<Leave>", lambda e: self._target(0.0))
        self.bind("<Button-1>", lambda e: self.cmd())
        self.bind("<Configure>", lambda e: self._paint())
        self._paint()

    def set_active(self, v):
        self.active = v
        self._paint()

    def _target(self, t):
        if self.active:
            return
        self._ht = t
        if not self._running:
            self._running = True
            self._anim()

    def _anim(self):
        d = self._ht - self._hp
        if abs(d) < 0.02:
            self._hp = self._ht
            self._running = False
            self._paint()
            return
        self._hp += d * 0.28
        self._paint()
        self.after(self.INTERVAL, self._anim)

    def _paint(self):
        self.delete("all")
        w = self.winfo_width() or 160
        h = self.winfo_height() or 36
        if self.active:
            bg = BG_RAISED
            fg = ACCENT
            self.create_rectangle(0, 3, 3, h - 3, fill=ACCENT, outline="")
        else:
            bg = lerp(BG_NAV, BG_HOVER, self._hp)
            fg = lerp(FG_DIM, FG, self._hp)
        self.configure(bg=bg)
        if self.show_label:
            self.create_text(14, h // 2, text=self.icon, fill=fg, font=F_SM, anchor="w")
            self.create_text(
                34,
                h // 2,
                text=self.text,
                fill=fg,
                font=F_NAV_A if self.active else F_NAV,
                anchor="w",
            )
        else:
            self.create_text(
                w // 2, h // 2, text=self.icon, fill=fg, font=F_SM, anchor="center"
            )


# ─── Collapsible card section ─────────────────────────────────────────────────
class Collapsible(tk.Frame):
    """A section with a clickable header that toggles body visibility."""

    def __init__(self, master, title, accent=GLOW, start_open=True, **kw):
        super().__init__(master, bg=BG, **kw)
        self._open = start_open
        # Header
        self.header = tk.Frame(self, bg=BG, cursor="hand2")
        self.header.pack(fill="x", padx=20, pady=(10, 0))
        self.arrow = tk.Label(
            self.header, text="▾" if start_open else "▸", font=F_SM, fg=FG_DIM, bg=BG
        )
        self.arrow.pack(side="left")
        self.title_lbl = tk.Label(
            self.header, text=title, font=F_SECTION, fg=FG, bg=BG, padx=6
        )
        self.title_lbl.pack(side="left")
        # Body
        self.body = tk.Frame(self, bg=BG)
        if start_open:
            self.body.pack(fill="x")
        # Bind clicks
        for w in (self.header, self.arrow, self.title_lbl):
            w.bind("<Button-1>", lambda e: self.toggle())
            w.bind("<Enter>", lambda e: self.arrow.configure(fg=ACCENT))
            w.bind("<Leave>", lambda e: self.arrow.configure(fg=FG_DIM))

    def toggle(self):
        self._open = not self._open
        self.arrow.configure(text="▾" if self._open else "▸")
        if self._open:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()

    def is_open(self):
        return self._open


# ─── Hover card ───────────────────────────────────────────────────────────────
class HoverCard(tk.Frame):
    """Card frame that subtly highlights on hover."""

    def __init__(self, master, accent=GLOW, **kw):
        super().__init__(master, bg=BG, **kw)
        self.accent_line = tk.Frame(self, bg=accent, height=2)
        self.accent_line.pack(fill="x")
        self.inner = tk.Frame(self, bg=BG_CARD, padx=16, pady=12)
        self.inner.pack(fill="x")
        self._accent = accent
        self.inner.bind("<Enter>", self._enter)
        self.inner.bind("<Leave>", self._leave)

    def _enter(self, e):
        self.inner.configure(bg=BG_HOVER)
        for w in self.inner.winfo_children():
            try:
                w.configure(bg=BG_HOVER)
            except:
                pass

    def _leave(self, e):
        self.inner.configure(bg=BG_CARD)
        for w in self.inner.winfo_children():
            try:
                w.configure(bg=BG_CARD)
            except:
                pass


# ─── Main app ────────────────────────────────────────────────────────────────
NAV_EXPANDED = 120
NAV_COLLAPSED = 40


class App(tk.Tk):
    def __init__(self, data):
        super().__init__()
        self.data = data
        self.current_export = ""

        # Window title with card number
        sus = data.get("sus", {})
        num = sus.get("number")
        card_str = ctrl_chars(num) if num else "Unknown"
        self.title(f"T-Mobilitat — {card_str}")

        self.configure(bg=BG)
        self.geometry("820x700")
        self.minsize(640, 480)

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.nav_expanded = False
        self._build_nav()
        self._build_content()
        self._apply_nav_state()
        self._show("overview")

    # ── Nav ───────────────────────────────────────────────────────────────────
    def _build_nav(self):
        self.nav = tk.Frame(self, bg=BG_NAV, width=NAV_COLLAPSED)
        self.nav.grid(row=0, column=0, sticky="nsew")
        self.nav.grid_propagate(False)
        self.nav.pack_propagate(False)

        # Hamburger
        hdr = tk.Frame(self.nav, bg=BG_NAV, pady=8)
        hdr.pack(fill="x")
        self.hamburger = tk.Canvas(
            hdr, width=32, height=32, bg=BG_NAV, highlightthickness=0, cursor="hand2"
        )
        self.hamburger.pack(side="left", padx=(6, 0))
        self.hamburger.bind("<Button-1>", lambda e: self._toggle_nav())
        self.hamburger.bind("<Enter>", lambda e: self._draw_hamburger(ACCENT))
        self.hamburger.bind("<Leave>", lambda e: self._draw_hamburger())
        self._draw_hamburger()

        self.brand_lbl = tk.Label(
            hdr, text="T-Mobilitat", font=(_FM, 10, "bold"), fg=FG, bg=BG_NAV
        )

        tk.Frame(self.nav, bg=BORDER, height=1).pack(fill="x", padx=6, pady=(0, 6))

        # Nav buttons
        self.nav_btns = {}
        for key, label, icon in [
            ("overview", "Overview", "◉"),
            ("passes", "Passes", "▤"),
            ("trip", "Last Trip", "▸"),
            ("raw", "Raw JSON", "{ }"),
        ]:
            b = NavBtn(self.nav, label, icon, lambda k=key: self._show(k))
            b.pack(fill="x", padx=3, pady=1)
            self.nav_btns[key] = b

        tk.Frame(self.nav, bg=BG_NAV).pack(fill="both", expand=True)

        # Bottom actions
        tk.Frame(self.nav, bg=BORDER, height=1).pack(fill="x", padx=6, pady=(0, 4))
        self.action_btns = []
        for txt, icon, cmd in [
            ("Copy", "📋", self._copy),
            ("Export", "💾", self._export),
        ]:
            lb = tk.Label(
                self.nav,
                text=icon,
                font=F_XS,
                fg=FG_DIM,
                bg=BG_NAV,
                padx=8,
                pady=4,
                anchor="center",
                cursor="hand2",
            )
            lb.pack(fill="x")
            lb.bind("<Enter>", lambda e, l=lb: l.configure(fg=FG))
            lb.bind("<Leave>", lambda e, l=lb: l.configure(fg=FG_DIM))
            lb.bind("<Button-1>", lambda e, c=cmd: c())
            self.action_btns.append((lb, icon, txt))

    def _draw_hamburger(self, color=None):
        c = self.hamburger
        c.delete("all")
        fg = color or FG_DIM
        for y in (10, 16, 22):
            c.create_line(7, y, 25, y, fill=fg, width=2, capstyle="round")

    def _toggle_nav(self):
        self.nav_expanded = not self.nav_expanded
        self._apply_nav_state()

    def _apply_nav_state(self):
        """Snap nav between expanded/collapsed."""
        w = NAV_EXPANDED if self.nav_expanded else NAV_COLLAPSED
        self.nav.configure(width=w)
        if self.nav_expanded:
            self.brand_lbl.pack(side="left", padx=(4, 0))
            for b in self.nav_btns.values():
                b.show_label = True
                b._paint()
            for lb, icon, txt in self.action_btns:
                lb.configure(text=f"{icon} {txt}", anchor="w", padx=6)
        else:
            self.brand_lbl.pack_forget()
            for b in self.nav_btns.values():
                b.show_label = False
                b._paint()
            for lb, icon, txt in self.action_btns:
                lb.configure(text=icon, anchor="center", padx=0)

    def _show(self, key):
        for k, b in self.nav_btns.items():
            b.set_active(k == key)
        {
            "overview": self._overview,
            "passes": self._passes,
            "trip": self._trip,
            "raw": self._raw,
        }[key]()

    # ── Scrollable content ────────────────────────────────────────────────────
    def _build_content(self):
        outer = tk.Frame(self, bg=BG)
        outer.grid(row=0, column=1, sticky="nsew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        self.scroll = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.content = tk.Frame(self.canvas, bg=BG)
        self.content.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self._cwin = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

    def _resize(self, e):
        self.canvas.itemconfigure(self._cwin, width=e.width)

    def _clear(self):
        for w in self.content.winfo_children():
            w.destroy()
        self.current_export = ""
        self.canvas.yview_moveto(0)

    # ── Widgets ───────────────────────────────────────────────────────────────
    def _title(self, parent, text, pad=(20, 6)):
        tk.Label(parent, text=text, font=F_SECTION, fg=FG, bg=BG, anchor="w").pack(
            fill="x", padx=20, pady=pad
        )

    def _card(self, parent=None, accent=GLOW, hover=False):
        parent = parent or self.content
        if hover:
            hc = HoverCard(parent, accent=accent)
            hc.pack(fill="x", padx=20, pady=4)
            return hc.inner
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="x", padx=20, pady=4)
        tk.Frame(wrap, bg=accent, height=2).pack(fill="x")
        c = tk.Frame(wrap, bg=BG_CARD, padx=16, pady=12)
        c.pack(fill="x")
        return c

    def _kv(self, parent, key, val, vc=FG, copyable=False):
        """Key-value row. If copyable, clicking the value copies it."""
        f = tk.Frame(parent, bg=parent["bg"])
        f.pack(fill="x", pady=1)
        tk.Label(
            f, text=key, font=F_SM, fg=FG_DIM, bg=parent["bg"], width=17, anchor="w"
        ).pack(side="left")
        vtext = str(val) if val is not None else "—"
        vlbl = tk.Label(
            f,
            text=vtext,
            font=F_SM,
            fg=vc,
            bg=parent["bg"],
            anchor="w",
            wraplength=400,
            justify="left",
        )
        vlbl.pack(side="left", padx=(6, 0))
        if copyable and val is not None:
            vlbl.configure(cursor="hand2")
            vlbl.bind("<Button-1>", lambda e, v=vtext: self._copy_value(v, vlbl))
            vlbl.bind("<Enter>", lambda e: vlbl.configure(fg=lerp(vc, "#ffffff", 0.3)))
            vlbl.bind("<Leave>", lambda e: vlbl.configure(fg=vc))

    def _copy_value(self, val, lbl):
        """Copy a value and flash the label."""
        self.clipboard_clear()
        self.clipboard_append(val)
        orig_fg = lbl.cget("fg")
        lbl.configure(fg=GREEN)
        self.after(400, lambda: lbl.configure(fg=orig_fg))

    def _pill(self, parent, label, value, color=ACCENT):
        f = tk.Frame(parent, bg=BG_RAISED, padx=10, pady=6)
        f.pack(side="left", padx=(0, 5), pady=2)
        tk.Label(f, text=label, font=F_XS, fg=FG_DIM, bg=BG_RAISED).pack(anchor="w")
        tk.Label(f, text=str(value), font=F_SUB, fg=color, bg=BG_RAISED).pack(
            anchor="w"
        )

    def _badge(self, parent, text, color=ACCENT):
        bg = lerp(color, BG_CARD, 0.84)
        return tk.Label(
            parent, text=f" {text} ", font=F_XS_B, fg=color, bg=bg, padx=3, pady=1
        )

    def _sep(self, parent=None):
        tk.Frame(parent or self.content, bg=BORDER, height=1).pack(
            fill="x", padx=20, pady=8
        )

    # ── OVERVIEW ──────────────────────────────────────────────────────────────
    def _overview(self):
        self._clear()
        sus = self.data.get("sus", {})
        atiu = self.data.get("atiu", {})
        user = self.data.get("user", {})
        passes = self.data.get("passes", {})
        profiles = self.data.get("profiles", [])

        # Hero card
        c = self._card(accent=ACCENT)
        top = tk.Frame(c, bg=BG_CARD)
        top.pack(fill="x")
        num = sus.get("number")
        tk.Label(
            top, text=ctrl_chars(num) if num else "—", font=F_CARD, fg=FG, bg=BG_CARD
        ).pack(side="left")
        valid = sus.get("is_valid", False)
        self._badge(top, "VALID" if valid else "INVALID", GREEN if valid else RED).pack(
            side="right", pady=4
        )

        meta = tk.Frame(c, bg=BG_CARD)
        meta.pack(fill="x", pady=(6, 0))
        parts = [sus.get("issuer_name", ""), sus.get("template_name", "")]
        st = atiu.get("status_desc", "")
        if st:
            parts.append(st)
        tk.Label(
            meta,
            text="  ·  ".join(p for p in parts if p),
            font=F_SM,
            fg=FG_DIM,
            bg=BG_CARD,
        ).pack(side="left")

        # Stats
        sf = tk.Frame(self.content, bg=BG)
        sf.pack(fill="x", padx=20, pady=(8, 2))
        self._pill(sf, "Events", atiu.get("event_counter", "—"))
        self._pill(sf, "Language", user.get("language_desc", "—"), ACCENT2)
        self._pill(sf, "Identity", user.get("identification_status_text", "—"), FG_DIM)

        # Active pass
        instances = passes.get("instances", [])
        ap = None
        for inst in instances:
            if inst.get("is_the_active_pass"):
                ap = inst
                break
        if not ap:
            for inst in instances:
                if inst.get("name"):
                    ap = inst
                    break
        if ap and ap.get("name"):
            sec = Collapsible(
                self.content, "Active Pass", accent=ACCENT, start_open=True
            )
            sec.pack(fill="x")
            self._render_pass(ap, expanded=False, parent=sec.body)

        # Card (SUS)
        sec = Collapsible(self.content, "Card (SUS)", start_open=True)
        sec.pack(fill="x")
        c = self._card(sec.body)
        self._kv(
            c, "Card number", ctrl_chars(num) if num else "—", ACCENT, copyable=True
        )
        self._kv(c, "Issuer", f"{sus.get('issuer_name','')}  (#{sus.get('issuer','')})")
        self._kv(
            c,
            "Template",
            f"{sus.get('template_name','')}  (#{sus.get('template_id','')})",
        )
        self._kv(c, "Valid", "Yes ✓" if valid else "No ✗", GREEN if valid else RED)

        # App (ATIU)
        sec = Collapsible(self.content, "Application (ATIU)", start_open=False)
        sec.pack(fill="x")
        c = self._card(sec.body)
        for k, vk in [
            ("Status", "status_desc"),
            ("Version", "version"),
            ("App ID", "app_id"),
            ("Structure", "structure_id"),
            ("Tech ID", "tech_id"),
            ("Key version", "key_version"),
            ("Issuer", "issuer_name"),
            ("Last SAM", "last_used_sam"),
            ("Events", "event_counter"),
            ("Delayed actions", "delayed_action_counter"),
        ]:
            v = atiu.get(vk)
            vc = FG
            if vk == "status_desc" and v and "anul" in str(v).lower():
                vc = YELLOW
            self._kv(c, k, v, vc, copyable=True)
        av = atiu.get("is_valid", False)
        self._kv(c, "Valid", "Yes ✓" if av else "No ✗", GREEN if av else RED)

        # User
        sec = Collapsible(self.content, "User", start_open=False)
        sec.pack(fill="x")
        c = self._card(sec.body)
        self._kv(c, "Identification", user.get("identification_status_text"))
        self._kv(c, "Language", user.get("language_desc"))
        self._kv(c, "Sensory aids", user.get("sensory_aids_desc"))

        # Profiles
        active_p = [p for p in profiles if p.get("is_valid")]
        if active_p:
            sec = Collapsible(self.content, "Profiles", start_open=True)
            sec.pack(fill="x")
            for pr in active_p:
                c = self._card(sec.body, accent=ACCENT2)
                row = tk.Frame(c, bg=BG_CARD)
                row.pack(fill="x")
                tk.Label(
                    row, text=pr.get("name", "—"), font=F_SUB, fg=FG, bg=BG_CARD
                ).pack(side="left")
                self._badge(row, "Active", GREEN).pack(side="right")
                tk.Label(
                    c,
                    text=f"{pr.get('owner_name','')}  ·  "
                    f"Valid {pr.get('init_val_date','?')} → {pr.get('end_val_date','?')}",
                    font=F_XS,
                    fg=FG_DIM,
                    bg=BG_CARD,
                ).pack(anchor="w", pady=(4, 0))

        tk.Frame(self.content, bg=BG, height=20).pack()
        self.current_export = pretty(self.data)

    # ── Pass renderer ─────────────────────────────────────────────────────────
    def _render_pass(self, inst, expanded=True, parent=None):
        pname, db = id_pass(inst)
        c = self._card(
            parent, accent=ACCENT if inst.get("is_the_active_pass") else BORDER
        )

        hdr = tk.Frame(c, bg=BG_CARD)
        hdr.pack(fill="x")
        tk.Label(hdr, text=pname, font=F_SUB, fg=FG, bg=BG_CARD).pack(side="left")
        if inst.get("is_the_active_pass"):
            self._badge(hdr, "ACTIVE", GREEN).pack(side="left", padx=(8, 0))
        if inst.get("is_exhausted"):
            self._badge(hdr, "EXHAUSTED", RED).pack(side="left", padx=(8, 0))
        elif not inst.get("is_valid") and not inst.get("container_free"):
            self._badge(hdr, "EXPIRED", YELLOW).pack(side="left", padx=(8, 0))
        st = inst.get("status_desc", "")
        if st:
            tk.Label(hdr, text=st, font=F_XS, fg=FG_DIM, bg=BG_CARD).pack(side="right")

        if db:
            cat = db["cat"]
            cl = {
                "trip": ("Trip-based", ACCENT),
                "time": ("Time-based", ACCENT2),
                "hybrid": ("Hybrid", YELLOW),
            }[cat]
            tk.Label(c, text=cl[0], font=F_XS, fg=cl[1], bg=BG_CARD).pack(
                anchor="w", pady=(2, 0)
            )

        ms = tk.Frame(c, bg=BG_CARD)
        ms.pack(fill="x", pady=(6, 2))
        if inst.get("owner_name"):
            self._pill(ms, "Owner", inst["owner_name"], FG_DIM)
        if inst.get("zones"):
            self._pill(ms, "Zones", inst["zones"], ACCENT2)
        if inst.get("magnetic_code"):
            self._pill(ms, "Mag", inst["magnetic_code"], FG_MUTED)

        pct, blabel, detail = progress_info(inst, db)
        if pct is not None:
            bf = tk.Frame(c, bg=BG_CARD)
            bf.pack(fill="x", pady=(8, 2))
            tk.Label(bf, text="Remaining", font=F_XS, fg=FG_DIM, bg=BG_CARD).pack(
                anchor="w"
            )
            ProgressBar(bf, target=pct, w=400, h=24, label=blabel).pack(
                anchor="w", pady=(3, 0)
            )
            if detail:
                tk.Label(bf, text=detail, font=F_XS, fg=FG_DIM, bg=BG_CARD).pack(
                    anchor="w", pady=(2, 0)
                )

        loads = inst.get("loads", [])
        for prev, curr in detect_swaps(loads):
            wf = tk.Frame(c, bg=lerp(YELLOW, BG_CARD, 0.88), padx=10, pady=5)
            wf.pack(fill="x", pady=(8, 0))
            tk.Label(
                wf, text="⚠  Load swap detected", font=F_XS_B, fg=YELLOW, bg=wf["bg"]
            ).pack(anchor="w")
            tk.Label(
                wf,
                text=f"Load #{curr.get('index')} purchased "
                f"{(curr.get('sale_datetime') or '?')[:10]} while "
                f"load #{prev.get('index')} valid until {prev.get('end_date','?')}",
                font=F_XS,
                fg=FG_DIM,
                bg=wf["bg"],
            ).pack(anchor="w", pady=(1, 0))

        if expanded and loads:
            tk.Frame(c, bg=BORDER, height=1).pack(fill="x", pady=(10, 6))
            tk.Label(c, text="Load History", font=F_SM_B, fg=FG_DIM, bg=BG_CARD).pack(
                anchor="w"
            )
            for ld in loads:
                lf = tk.Frame(c, bg=BG_RAISED, padx=10, pady=6)
                lf.pack(fill="x", pady=3)
                lh = tk.Frame(lf, bg=BG_RAISED)
                lh.pack(fill="x")
                tk.Label(
                    lh,
                    text=f"Load #{ld.get('index','?')}",
                    font=F_SM_B,
                    fg=FG,
                    bg=BG_RAISED,
                ).pack(side="left")
                if ld.get("is_the_active_load"):
                    self._badge(lh, "CURRENT", GREEN).pack(side="left", padx=(8, 0))
                elif ld.get("is_expired"):
                    self._badge(lh, "EXPIRED", FG_DIM).pack(side="left", padx=(8, 0))
                sdt = pdate(ld.get("sale_datetime"))
                ss = sdt.strftime("%d %b %Y %H:%M") if sdt else "—"
                for k, v in [
                    ("Sold", ss),
                    ("Period", f"{ld.get('init_date','?')} → {ld.get('end_date','?')}"),
                    ("Agency", ld.get("sale_agency_name", "—")),
                    ("Trip bal.", ld.get("trip_balance", "—")),
                    ("Zone", ld.get("first_entry_zone_name", "—")),
                ]:
                    r = tk.Frame(lf, bg=BG_RAISED)
                    r.pack(fill="x")
                    tk.Label(
                        r,
                        text=k,
                        font=F_XS,
                        fg=FG_MUTED,
                        bg=BG_RAISED,
                        width=10,
                        anchor="w",
                    ).pack(side="left")
                    tk.Label(r, text=str(v), font=F_XS, fg=FG2, bg=BG_RAISED).pack(
                        side="left"
                    )

    # ── PASSES ────────────────────────────────────────────────────────────────
    def _passes(self):
        self._clear()
        self._title(self.content, "Passes & Loads")
        passes = self.data.get("passes", {})
        purse = passes.get("purse", {})
        if purse.get("allow_companion") is not None:
            c = self._card(accent=ACCENT2)
            row = tk.Frame(c, bg=BG_CARD)
            row.pack(fill="x")
            tk.Label(row, text="Purse", font=F_SM_B, fg=FG_DIM, bg=BG_CARD).pack(
                side="left"
            )
            comp = purse.get("allow_companion", False)
            self._badge(
                row,
                "Companion ✓" if comp else "No companion",
                GREEN if comp else FG_DIM,
            ).pack(side="right")
        empty = True
        for inst in passes.get("instances", []):
            if inst.get("container_free") and not inst.get("name"):
                continue
            empty = False
            self._render_pass(inst, expanded=True)
        if empty:
            c = self._card()
            tk.Label(
                c, text="No pass instances.", font=F_BODY, fg=FG_DIM, bg=BG_CARD
            ).pack(anchor="w")
        tk.Frame(self.content, bg=BG, height=20).pack()
        self.current_export = pretty(passes)

    # ── LAST TRIP ─────────────────────────────────────────────────────────────
    def _trip(self):
        self._clear()
        self._title(self.content, "Last Trip")
        lt = self.data.get("last_trip", {})
        c = self._card()
        dt = pdate(lt.get("first_stage_datetime"))
        if dt:
            tk.Label(
                c, text=dt.strftime("%A, %d %B %Y"), font=F_SUB, fg=FG, bg=BG_CARD
            ).pack(anchor="w")
            tk.Label(
                c, text=dt.strftime("%H:%M"), font=F_BIG, fg=ACCENT, bg=BG_CARD
            ).pack(anchor="w")
        sf = tk.Frame(c, bg=BG_CARD)
        sf.pack(fill="x", pady=(8, 0))
        self._pill(sf, "Transfers", lt.get("num_transfers", 0))
        self._pill(sf, "Users", lt.get("total_users", 1), ACCENT2)
        self._pill(sf, "Pass #", lt.get("pass_index", "—"), FG_DIM)

        for s in lt.get("stages", []):
            tk.Frame(self.content, bg=BORDER, height=1).pack(fill="x", padx=20, pady=8)
            sc = self._card(hover=True)
            co = s.get("company_name", "")
            if co == "FMB":
                transport, icon, src = "Metro", "🚇", s.get("on_station", {})
            elif co == "TB":
                transport, icon, src = "Bus", "🚌", s.get("on_board", {})
            else:
                transport, icon, src = (
                    co,
                    "🚊",
                    s.get("on_station", s.get("on_board", {})),
                )
            entry = src.get("entry", {})
            station = entry.get("station_interop_name", "—")
            edt = pdate(entry.get("datetime"))
            es = edt.strftime("%H:%M · %d %b %Y") if edt else "—"
            tk.Label(
                sc,
                text=f"{icon}  Stage {s.get('index','?')} — {transport}",
                font=F_SUB,
                fg=FG,
                bg=BG_CARD,
            ).pack(anchor="w")
            self._kv(sc, "Station", station, ACCENT, copyable=True)
            self._kv(sc, "Entry", es, copyable=True)
            ln = entry.get("associated_index")
            if ln:
                self._kv(sc, "Line", ln)
            ex = src.get("exit", {}).get("station_interop_name", "")
            if ex:
                self._kv(sc, "Exit", ex, YELLOW, copyable=True)

        tk.Frame(self.content, bg=BG, height=20).pack()
        self.current_export = pretty(lt)

    # ── RAW JSON ──────────────────────────────────────────────────────────────
    def _raw(self):
        self._clear()
        self._title(self.content, "Raw JSON")
        c = self._card()
        txt = tk.Text(
            c,
            wrap=tk.WORD,
            font=F_MONO,
            height=34,
            bg=BG_RAISED,
            fg=FG2,
            insertbackground=FG,
            selectbackground=GLOW,
            borderwidth=0,
            padx=10,
            pady=10,
        )
        txt.pack(fill="both", expand=True)
        txt.insert(tk.END, pretty(self.data))
        txt.configure(state="disabled")
        self.current_export = pretty(self.data)

    # ── Actions ───────────────────────────────────────────────────────────────
    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.current_export or pretty(self.data))
        t = self.title()
        self.title(t.split("—")[0] + "— Copied ✓")
        self.after(1200, lambda: self.title(t))

    def _export(self):
        s = self.current_export or pretty(self.data)
        with open("t_mobilitat_export.txt", "w", encoding="utf-8") as f:
            f.write(s)
        t = self.title()
        self.title(t.split("—")[0] + "— Exported ✓")
        self.after(1200, lambda: self.title(t))


# ─── Public API ───────────────────────────────────────────────────────────────
def launch_gui(json_string: str):
    parsed = json.loads(json_string)
    App(parsed).mainloop()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            launch_gui(f.read())
    else:
        sample = '{"sus":{"number":7245365,"issuer":5,"issuer_name":"ATM Barcelona","template_id":1,"template_name":"Targeta T-mobilitat","is_valid":true},"atiu":{"version":1,"global_structure_id":3,"mapping_id":1,"tech_id":3,"key_version":1,"app_id":1,"structure_id":1,"status":2,"status_desc":"Anul\u00b7lat","issuer":5,"issuer_name":"ATM Barcelona","last_used_sam":90170,"last_modification_time":"","event_counter":125,"delayed_action_counter":1,"is_valid":false},"user":{"identification_status":2,"identification_status_text":"Personalitzat","language":1,"language_desc":"Catal\u00e0","sensory_aids":0,"sensory_aids_desc":"Sense ajudes"},"profiles":[{"index":0,"code":2,"owner":5,"owner_name":"ATM Barcelona","name":"Jove","init_val_date":"2023-06-19","end_val_date":"2029-12-30","additional_info":0,"is_valid":true,"is_expired":false,"container_free":false,"can_be_removed":false}],"passes":{"selected_pass":1,"purse":{"status_desc":"","allow_companion":true},"instances":[{"index":1,"code":376,"owner":5,"owner_name":"ATM Barcelona","name":"T-jove","magnetic_code":440,"status":0,"status_desc":"Actiu","zones":7,"is_trip_based":false,"validation_by_trip_regularization_balance":false,"restrictions":{"allow_companion":false},"regularizations":{},"is_valid":true,"is_exhausted":true,"container_free":false,"can_be_removed":false,"can_be_load":false,"can_be_reload":false,"is_the_active_pass":true,"can_activate_companion":false,"loads":[{"index":0,"sale_datetime":"2024-03-21T12:54:20","cancelled":false,"trip_balance":38,"sale_agency":1,"sale_agency_name":"FMB","init_date":"2024-03-21","end_date":"2024-06-18","first_entry_zone":1,"first_entry_zone_name":"1","is_valid":false,"is_expired":true,"is_exhausted":false,"container_free":false,"can_be_reload":false,"can_be_cancelled":false,"is_the_active_load":false,"has_been_validated":true,"can_change_fare":false},{"index":1,"sale_datetime":"2023-11-30T12:22:10","cancelled":false,"trip_balance":57,"sale_agency":1,"sale_agency_name":"FMB","init_date":"2023-12-20","end_date":"2024-03-18","first_entry_zone":1,"first_entry_zone_name":"1","is_valid":false,"is_expired":true,"is_exhausted":false,"container_free":false,"can_be_reload":false,"can_be_cancelled":false,"is_the_active_load":false,"has_been_validated":true,"can_change_fare":false}],"purse_balance":0,"trip_balance":0,"exp_date":"","is_exit":false,"is_transfer":false,"is_access_by_exception":false,"accumulated_zone_leaps":0,"stage_zone_leaps":0}]},"last_trip":{"pass_index":1,"last_access_event_counter":124,"users_in_stage":1,"total_users":1,"max_transfer_users":1,"first_stage_datetime":"2024-04-01T08:25:29","stages":[{"index":0,"company":1,"company_name":"FMB","on_station":{"entry":{"station_interop":957,"station_interop_name":"Foneria","datetime":"2024-04-01T08:25:29","associated_index":9,"railway_station_name":""},"exit":{"station_interop_name":"","railway_station_name":""}}}],"num_transfers":0},"sus_image":{"data":"","length_in_bits":0}}'
        launch_gui(sample)
