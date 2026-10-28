#!/usr/bin/env python3
"""Builds mockups/dashboard-round4b.html (static, zero-JS, no external assets).

Real numbers come from tests/fixtures/status-metered.json. Panels marked "Sample"
use synthetic splits that sum exactly to the fixture totals, because /status does
not carry per-day or per-model metered usage yet. Run: python3 mockups/build-mockup.py
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ST = json.load(open(os.path.join(ROOT, "tests", "fixtures", "status-metered.json")))
M = ST["metering"]

# ---------------------------------------------------------------- provider marks
# Mono marks from lobehub/lobe-icons (MIT, packages/static-svg/icons/*.svg), fill=currentColor.
# Logos remain trademarks of their owners; used here only to identify each model's maker.
LOGOS = {
    "qwen": ("Qwen", "M19.713 2.825h-5.907c0-.251-.066-.503-.196-.728L12.819.728A1.46 1.46 0 0 0 11.559 0h-1.58c-.52 0-1 .275-1.26.728l-2.42 4.19a1.45 1.45 0 0 0 0 1.453l.791 1.37c.26.448.74.727 1.26.727h11.36c.52 0 1-.275 1.26-.728l.79-1.37a1.45 1.45 0 0 0 0-1.451l-.79-1.37a1.46 1.46 0 0 0-1.26-.728zM.195 9.905l2.951 5.115a1.46 1.46 0 0 0-.531.531l-.791 1.37a1.45 1.45 0 0 0 0 1.452l.79 1.37c.26.448.74.727 1.26.727h4.84c.52 0 1-.275 1.26-.728l.79-1.37a1.45 1.45 0 0 0 0-1.451L5.086 7.083a1.46 1.46 0 0 0-1.26-.728h-1.58c-.52 0-1 .276-1.26.728l-.79 1.37a1.45 1.45 0 0 0 0 1.452m15.888 13.367 2.951-5.115c.217.125.469.196.728.196h1.582c.52 0 1-.275 1.26-.728l.79-1.37a1.45 1.45 0 0 0 0-1.451l-2.42-4.191a1.46 1.46 0 0 0-1.259-.728h-1.582c-.52 0-1 .276-1.259.728l-5.678 9.838a1.45 1.45 0 0 0 0 1.452l.79 1.37c.26.448.74.727 1.26.727h1.582c.52 0 1-.275 1.26-.728z"),
    "meta": ("Meta", "M6.897 4c1.915 0 3.516.932 5.43 3.376l.282-.373c.19-.246.383-.484.58-.71l.313-.35C14.588 4.788 15.792 4 17.225 4c1.273 0 2.469.557 3.491 1.516l.218.213c1.73 1.765 2.917 4.71 3.053 8.026l.011.392.002.25c0 1.501-.28 2.759-.818 3.7l-.14.23-.108.153c-.301.42-.664.758-1.086 1.009l-.265.142-.087.04a3.493 3.493 0 01-.302.118 4.117 4.117 0 01-1.33.208c-.524 0-.996-.067-1.438-.215-.614-.204-1.163-.56-1.726-1.116l-.227-.235c-.753-.812-1.534-1.976-2.493-3.586l-1.43-2.41-.544-.895-1.766 3.13-.343.592C7.597 19.156 6.227 20 4.356 20c-1.21 0-2.205-.42-2.936-1.182l-.168-.184c-.484-.573-.837-1.311-1.043-2.189l-.067-.32a8.69 8.69 0 01-.136-1.288L0 14.468c.002-.745.06-1.49.174-2.23l.1-.573c.298-1.53.828-2.958 1.536-4.157l.209-.34c1.177-1.83 2.789-3.053 4.615-3.16L6.897 4zm-.033 2.615l-.201.01c-.83.083-1.606.673-2.252 1.577l-.138.199-.01.018c-.67 1.017-1.185 2.378-1.456 3.845l-.004.022a12.591 12.591 0 00-.207 2.254l.002.188c.004.18.017.36.04.54l.043.291c.092.503.257.908.486 1.208l.117.137c.303.323.698.492 1.17.492 1.1 0 1.796-.676 3.696-3.641l2.175-3.4.454-.701-.139-.198C9.11 7.3 8.084 6.616 6.864 6.616zm10.196-.552l-.176.007c-.635.048-1.223.359-1.82.933l-.196.198c-.439.462-.887 1.064-1.367 1.807l.266.398c.18.274.362.56.55.858l.293.475 1.396 2.335.695 1.114c.583.926 1.03 1.6 1.408 2.082l.213.262c.282.326.529.54.777.673l.102.05c.227.1.457.138.718.138.176.002.35-.023.518-.073.338-.104.61-.32.813-.637l.095-.163.077-.162c.194-.459.29-1.06.29-1.785l-.006-.449c-.08-2.871-.938-5.372-2.2-6.798l-.176-.189c-.67-.683-1.444-1.074-2.27-1.074z"),
    "gemma": ("Gemma", "M12.34 5.953a8.233 8.233 0 01-.247-1.125V3.72a8.25 8.25 0 015.562 2.232H12.34zm-.69 0c.113-.373.199-.755.257-1.145V3.72a8.25 8.25 0 00-5.562 2.232h5.304zm-5.433.187h5.373a7.98 7.98 0 01-.267.696 8.41 8.41 0 01-1.76 2.65L6.216 6.14zm-.264-.187H2.977v.187h2.915a8.436 8.436 0 00-2.357 5.767H0v.186h3.535a8.436 8.436 0 002.357 5.767H2.977v.186h2.976v2.977h.187v-2.915a8.436 8.436 0 005.767 2.357V24h.186v-3.535a8.436 8.436 0 005.767-2.357v2.915h.186v-2.977h2.977v-.186h-2.915a8.436 8.436 0 002.357-5.767H24v-.186h-3.535a8.436 8.436 0 00-2.357-5.767h2.915v-.187h-2.977V2.977h-.186v2.915a8.436 8.436 0 00-5.767-2.357V0h-.186v3.535A8.436 8.436 0 006.14 5.892V2.977h-.187v2.976zm6.14 14.326a8.25 8.25 0 005.562-2.233H12.34c-.108.367-.19.743-.247 1.126v1.107zm-.186-1.087a8.015 8.015 0 00-.258-1.146H6.345a8.25 8.25 0 005.562 2.233v-1.087zm-8.186-7.285h1.107a8.23 8.23 0 001.125-.247V6.345a8.25 8.25 0 00-2.232 5.562zm1.087.186H3.72a8.25 8.25 0 002.232 5.562v-5.304a8.012 8.012 0 00-1.145-.258zm15.47-.186a8.25 8.25 0 00-2.232-5.562v5.315c.367.108.743.19 1.126.247h1.107zm-1.086.186c-.39.058-.772.144-1.146.258v5.304a8.25 8.25 0 002.233-5.562h-1.087zm-1.332 5.69V12.41a7.97 7.97 0 00-.696.267 8.409 8.409 0 00-2.65 1.76l3.346 3.346zm0-6.18v-5.45l-.012-.013h-5.451c.076.235.162.468.26.696a8.698 8.698 0 001.819 2.688 8.698 8.698 0 002.688 1.82c.228.097.46.183.696.259zM6.14 17.848V12.41c.235.078.468.167.696.267a8.403 8.403 0 012.688 1.799 8.404 8.404 0 011.799 2.688c.1.228.19.46.267.696H6.152l-.012-.012zm0-6.245V6.326l3.29 3.29a8.716 8.716 0 01-2.594 1.728 8.14 8.14 0 01-.696.259zm6.257 6.257h5.277l-3.29-3.29a8.716 8.716 0 00-1.728 2.594 8.135 8.135 0 00-.259.696zm-2.347-7.81a9.435 9.435 0 01-2.88 1.96 9.14 9.14 0 012.88 1.94 9.14 9.14 0 011.94 2.88 9.435 9.435 0 011.96-2.88 9.14 9.14 0 012.88-1.94 9.435 9.435 0 01-2.88-1.96 9.434 9.434 0 01-1.96-2.88 9.14 9.14 0 01-1.94 2.88z"),
    "microsoft": ("Microsoft", "M11.49 2H2v9.492h9.492V2h-.002zM22 2h-9.492v9.492H22V2zM11.49 12.508H2V22h9.492v-9.492h-.002zM22 12.508h-9.492V22H22v-9.492z"),
}
OLLAMA = "M7.905 1.09c.216.085.411.225.588.41.295.306.544.744.734 1.263.191.522.315 1.1.362 1.68a5.054 5.054 0 012.049-.636l.051-.004c.87-.07 1.73.087 2.48.474.101.053.2.11.297.17.05-.569.172-1.134.36-1.644.19-.52.439-.957.733-1.264a1.67 1.67 0 01.589-.41c.257-.1.53-.118.796-.042.401.114.745.368 1.016.737.248.337.434.769.561 1.287.23.934.27 2.163.115 3.645l.053.04.026.019c.757.576 1.284 1.397 1.563 2.35.435 1.487.216 3.155-.534 4.088l-.018.021.002.003c.417.762.67 1.567.724 2.4l.002.03c.064 1.065-.2 2.137-.814 3.19l-.007.01.01.024c.472 1.157.62 2.322.438 3.486l-.006.039a.651.651 0 01-.747.536.648.648 0 01-.54-.742c.167-1.033.01-2.069-.48-3.123a.643.643 0 01.04-.617l.004-.006c.604-.924.854-1.83.8-2.72-.046-.779-.325-1.544-.8-2.273a.644.644 0 01.18-.886l.009-.006c.243-.159.467-.565.58-1.12a4.229 4.229 0 00-.095-1.974c-.205-.7-.58-1.284-1.105-1.683-.595-.454-1.383-.673-2.38-.61a.653.653 0 01-.632-.371c-.314-.665-.772-1.141-1.343-1.436a3.288 3.288 0 00-1.772-.332c-1.245.099-2.343.801-2.67 1.686a.652.652 0 01-.61.425c-1.067.002-1.893.252-2.497.703-.522.39-.878.935-1.066 1.588a4.07 4.07 0 00-.068 1.886c.112.558.331 1.02.582 1.269l.008.007c.212.207.257.53.109.785-.36.622-.629 1.549-.673 2.44-.05 1.018.186 1.902.719 2.536l.016.019a.643.643 0 01.095.69c-.576 1.236-.753 2.252-.562 3.052a.652.652 0 01-1.269.298c-.243-1.018-.078-2.184.473-3.498l.014-.035-.008-.012a4.339 4.339 0 01-.598-1.309l-.005-.019a5.764 5.764 0 01-.177-1.785c.044-.91.278-1.842.622-2.59l.012-.026-.002-.002c-.293-.418-.51-.953-.63-1.545l-.005-.024a5.352 5.352 0 01.093-2.49c.262-.915.777-1.701 1.536-2.269.06-.045.123-.09.186-.132-.159-1.493-.119-2.73.112-3.67.127-.518.314-.95.562-1.287.27-.368.614-.622 1.015-.737.266-.076.54-.059.797.042zm4.116 9.09c.936 0 1.8.313 2.446.855.63.527 1.005 1.235 1.005 1.94 0 .888-.406 1.58-1.133 2.022-.62.375-1.451.557-2.403.557-1.009 0-1.871-.259-2.493-.734-.617-.47-.963-1.13-.963-1.845 0-.707.398-1.417 1.056-1.946.668-.537 1.55-.849 2.485-.849zm0 .896a3.07 3.07 0 00-1.916.65c-.461.37-.722.835-.722 1.25 0 .428.21.829.61 1.134.455.347 1.124.548 1.943.548.799 0 1.473-.147 1.932-.426.463-.28.7-.686.7-1.257 0-.423-.246-.89-.683-1.256-.484-.405-1.14-.643-1.864-.643zm-5.04-1.919c.478 0 .867.39.867.871a.87.87 0 01-.868.871.87.87 0 01-.867-.87.87.87 0 01.867-.872zm8.706 0c.48 0 .868.39.868.871a.87.87 0 01-.868.871.87.87 0 01-.867-.87.87.87 0 01.867-.872z"


def provider_of(model):
    n = model.lower()
    if n.startswith("qwen"):
        return "qwen"
    if "gemma" in n:
        return "gemma"
    if n.startswith("llama"):
        return "meta"
    if n.startswith("phi"):
        return "microsoft"
    return None


def sprite():
    out = ['<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>']
    for key, (_, d) in LOGOS.items():
        out.append('<symbol id="lg-%s" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="%s"/></symbol>' % (key, d))
    out.append('<symbol id="lg-ollama" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="%s"/></symbol>' % OLLAMA)
    out.append("</defs></svg>")
    return "".join(out)


def logo(model, size=20, cls="logo"):
    p = provider_of(model)
    if not p:
        return '<span class="%s mono-tile" aria-hidden="true">%s</span>' % (cls, model[:1].upper())
    return '<span class="%s" title="%s"><svg width="%d" height="%d" aria-hidden="true" focusable="false"><use href="#lg-%s"/></svg></span>' % (cls, LOGOS[p][0], size, size, p)


def n(v):
    return "{:,}".format(v)


# ---------------------------------------------------------------- sample split
# Model totals sum to metering.eval_tokens_total (23,110). Day weights follow the
# fixture's daily probe counts, bent per model so columns do not all share one mix.
MODELS = [  # (name, css var, total, maker label)
    ("qwen3:4b", "m1", 13420, "Qwen"),
    ("llama3.2:3b", "m2", 5260, "Meta"),
    ("qwen2.5:0.5b", "m3", 2890, "Qwen"),
    ("gemma2:2b", "m4", 1190, "Google"),
    ("phi4-mini + 1 more", "m0", 350, "Microsoft, Qwen"),
]
assert sum(m[2] for m in MODELS) == M["eval_tokens_total"]
DAILY = ST["activity"]["daily"]
dcount = [d["count"] for d in DAILY]
bend = [
    lambda i: 0.45 + i / 13,
    lambda i: max(0.15, 1 - abs(i - 8) / 7),
    lambda i: 1.6 - i / 11,
    lambda i: 1.0 if i < 9 else 0.35,
    lambda i: 1.0 if i >= 10 else 0.0,
]
SPLIT = []
for (name, var, total, _), f in zip(MODELS, bend):
    w = [dcount[i] * f(i) for i in range(14)]
    row = [round(total * x / sum(w)) for x in w]
    last = max(i for i in range(14) if w[i] > 0)
    row[last] += total - sum(row)
    SPLIT.append(row)
COLS = [sum(r[i] for r in SPLIT) for i in range(14)]
assert sum(COLS) == M["eval_tokens_total"]

AGENTS = [("kiro-spar", 11200), ("codex-spar", 7050), ("muse-status", 3120), ("unknown", 1740)]
assert sum(a[1] for a in AGENTS) == M["eval_tokens_total"]

# ---------------------------------------------------------------- cost estimate
# Low / base / high reference rates in USD per 1M tokens (input, output). Assumptions,
# not quotes: set per deployment. Electricity is not netted (not measured).
RATES = [("Low", 0.05, 0.10), ("Base", 0.15, 0.60), ("High", 3.00, 15.00)]
COST = {k: (M["prompt_tokens_total"] * i + M["eval_tokens_total"] * o) / 1e6 for k, i, o in RATES}


def usd(v):
    if v < 0.01:
        return "$%.3f" % v
    if v < 1:
        return "$%.2f" % v if v >= 0.1 else "$%.3f" % v
    return "${:,.2f}".format(v)


# ---------------------------------------------------------------- charts
def stacked_chart():
    x0, x1, yb, yt, top = 48, 632, 196, 16, 6000
    slot = (x1 - x0) / 14
    bw = slot - 12
    Y = lambda v: (yb - yt) * v / top
    p = ['<svg class="chart" style="--s:.82" viewBox="0 0 640 224" role="img" aria-labelledby="use-t">',
         '<title id="use-t">Sample: generated tokens per day by model, 14 to 27 October; busiest day 27 October with %s.</title>' % n(COLS[-1])]
    for v in (2000, 4000, 6000):
        y = yb - Y(v)
        p.append('<line class="gl" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f" text-anchor="end">%dk</text>' % (x0, y, x1, y, x0 - 8, y + 5, v // 1000))
    p.append('<text class="tick" x="%d" y="%d" text-anchor="end">0</text>' % (x0 - 8, yb + 5))
    for i in range(14):
        x = x0 + i * slot + 6
        y = yb
        seg = []
        for (name, var, _, _), row in zip(MODELS, SPLIT):
            h = Y(row[i])
            if h <= 0:
                continue
            y -= h
            seg.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="var(--%s)"><title>%s: %s</title></rect>' % (x, y, bw, h, var, name, n(row[i])))
        if seg:
            p.append('<g class="col" style="--i:%d"><title>Oct %d: %s tokens</title>%s</g>' % (i, 14 + i, n(COLS[i]), "".join(seg)))
    p.append('<line class="axis" x1="%d" y1="%d" x2="%d" y2="%d"/>' % (x0, yb, x1, yb))
    for i in (1, 4, 7, 10, 13):
        p.append('<text class="tick" x="%.1f" y="218" text-anchor="middle">Oct %d</text>' % (x0 + i * slot + slot / 2, 14 + i))
    p.append("</svg>")
    return "".join(p)


def leaderboard():
    total = M["eval_tokens_total"]
    li = []
    for rank, (name, var, tok, maker) in enumerate(MODELS, 1):
        model_for_logo = "phi4-mini" if var == "m0" else name
        li.append('<li style="--i:%d"><span class="rk num">%d.</span>%s<span class="nm"><b>%s</b><span>by %s</span></span><span class="dot" style="background:var(--%s)" aria-hidden="true"></span><span class="val"><b class="num">%s</b><span class="num">%.1f%%</span></span></li>'
                  % (rank, rank, logo(model_for_logo, 18, "logo tile"), name, maker, var, n(tok), 100 * tok / total))
    return '<ol class="board">' + "".join(li) + "</ol>"


def sankey():
    W, H = 760, 320
    total = M["eval_tokens_total"]
    k = 236 / total
    lx, mx, rx = 132, 372, 600
    out = ['<svg class="chart" style="--s:1.12" viewBox="0 0 %d %d" role="img" aria-labelledby="flow-t">' % (W, H),
           '<title id="flow-t">Sample: generated tokens flow from agents through the metering proxy into models. %s</title>' % "; ".join("%s %s" % (a, n(v)) for a, v in AGENTS)]

    def band(xa, a0, a1, xb, b0, b1, fill, op):
        xm = (xa + xb) / 2
        return '<path d="M%.1f %.1f C%.1f %.1f %.1f %.1f %.1f %.1f L%.1f %.1f C%.1f %.1f %.1f %.1f %.1f %.1fZ" fill="%s" fill-opacity="%s"/>' % (
            xa, a0, xm, a0, xm, b0, xb, b0, xb, b1, xm, b1, xm, a1, xa, a1, fill, op)

    # left: agents (self-declared names) -> meter
    y, my = 20, 32
    for a, v in AGENTS:
        h = v * k
        out.append(band(lx + 6, y, y + h, mx, my, my + h, "var(--muted)", ".16"))
        out.append('<rect x="%d" y="%.1f" width="6" height="%.1f" rx="1" fill="var(--muted)"/>' % (lx, y, h))
        out.append('<text class="lbl" x="%d" y="%.1f" text-anchor="end">%s <tspan class="lbl2 num">%s</tspan></text>' % (lx - 10, y + h / 2 + 5, a, n(v)))
        y += max(h, 18) + 10
        my += h
    # meter node (focal)
    out.append('<rect class="meter" x="%d" y="32" width="12" height="%.1f" rx="2"/>' % (mx, total * k))
    out.append('<text class="lbl acc" x="%d" y="22" text-anchor="middle">proxy tap · measured</text>' % (mx + 6))
    # right: meter -> models
    y, my = 14, 32
    for (name, var, tok, maker) in MODELS:
        h = tok * k
        out.append(band(mx + 12, my, my + h, rx, y, y + h, "var(--%s)" % var, ".28"))
        out.append('<rect x="%d" y="%.1f" width="6" height="%.1f" rx="1" fill="var(--%s)"/>' % (rx, y, max(h, 2), var))
        cy = y + max(h, 2) / 2
        p = provider_of("phi4-mini" if var == "m0" else name)
        out.append('<use href="#lg-%s" x="%d" y="%.1f" width="16" height="16" class="lg"/>' % (p, rx + 14, cy - 8))
        out.append('<text class="lbl" x="%d" y="%.1f">%s <tspan class="lbl2 num">%s</tspan></text>' % (rx + 36, cy + 5, name, n(tok)))
        y += max(h, 2) + (12 if h > 20 else 18)
        my += h
    # leaks: not in the sums
    ly = 32 + total * k + 12
    out.append('<path d="M%d %.1f V%.1f" class="leak"/>' % (mx + 6, ly - 6, ly + 14))
    out.append('<text class="lbl2" x="%d" y="%.1f" text-anchor="middle">%d streams without usage · 1 failed (502) · not counted</text>' % (mx + 6, ly + 34, M["unmetered_stream_calls"]))
    out.append("</svg>")
    return "".join(out)


def cost_range():
    lo, base, hi = COST["Low"], COST["Base"], COST["High"]
    X = lambda v: 14 + (math.log10(v) + 3) / 3 * 332
    p = ['<svg class="chart" style="--s:1" viewBox="0 0 360 74" role="img" aria-labelledby="cost-t"><title id="cost-t">Estimated cloud-equivalent cost avoided: low %s, base %s, high %s.</title>' % (usd(lo), usd(base), usd(hi))]
    p.append('<line class="axis" x1="14" y1="30" x2="346" y2="30"/>')
    for v, t in ((0.001, "$0.001"), (0.01, "$0.01"), (0.1, "$0.10"), (1, "$1")):
        p.append('<line class="gl" x1="%.1f" y1="24" x2="%.1f" y2="36"/><text class="tick" x="%.1f" y="66" text-anchor="middle">%s</text>' % (X(v), X(v), X(v), t))
    p.append('<rect class="rng" x="%.1f" y="25" width="%.1f" height="10" rx="5"/>' % (X(lo), X(hi) - X(lo)))
    p.append('<circle class="base-dot" cx="%.1f" cy="30" r="7"/>' % X(base))
    p.append("</svg>")
    return "".join(p)


def ring():
    loaded = [m for m in ST["models"] if m["loaded"]]
    mb = sum(m["size_mb"] for m in loaded)
    frac = mb / 8192
    r, c = 44, 2 * math.pi * 44
    return ('<svg class="ring" style="--s:1.07" viewBox="0 0 120 120" role="img" aria-label="%s MB of 8 GB RAM held by loaded model weights">'
            '<circle cx="60" cy="60" r="%d" class="ring-t"/><circle cx="60" cy="60" r="%d" class="ring-v" stroke-dasharray="%.1f %.1f" transform="rotate(-90 60 60)"/>'
            '<text x="60" y="58" text-anchor="middle" class="ring-n num">%.1f%%</text><text x="60" y="76" text-anchor="middle" class="ring-l">of 8 GB</text></svg>') % (n(mb), r, r, c * frac, c, 100 * frac), mb, loaded


def ramfit():
    rows = []
    for m in sorted([m for m in ST["models"]], key=lambda m: -m["size_mb"]) + [{"name": "qwen2.5:14b", "size_mb": 8572, "loaded": False}]:
        over = m["size_mb"] > 8192
        w = min(100.0, 100 * m["size_mb"] / 8192)
        cls = "over" if over else ("on" if m["loaded"] else "")
        note = '<span class="chip chip-bad"><span class="g" aria-hidden="true">■</span>Too big</span>' if over else ('<span class="chip chip-ok"><span class="g" aria-hidden="true">●</span>Loaded</span>' if m["loaded"] else "")
        rows.append('<li><span class="mc">%s<span>%s</span></span><span class="fit %s" aria-hidden="true"><i style="width:%.1f%%"></i></span><span class="num">%.1f GB</span><span>%s</span></li>' % (logo(m["name"], 14, "logo"), m["name"], cls, w, m["size_mb"] / 1024, note))
    return '<ul class="ramfit">' + "".join(rows) + '</ul><p class="fine">Weights on disk against the 8 GB box; KV cache and macOS need the rest.</p>'


def heat():
    hi = max(dcount) or 1
    p = ['<svg class="chart" style="--s:1.2" viewBox="0 0 560 64" role="img" aria-labelledby="heat-t"><title id="heat-t">Probe checks per day: %s.</title>' % ", ".join("Oct %d %d" % (14 + i, c) for i, c in enumerate(dcount))]
    for i, c in enumerate(dcount):
        x = i * 40
        lvl = 0 if c == 0 else min(4, 1 + int(3.999 * c / hi))
        op = [0, .22, .45, .7, 1][lvl]
        if lvl:
            p.append('<rect x="%d" y="0" width="36" height="36" rx="6" fill="var(--accent)" fill-opacity="%s"/>' % (x, op))
        else:
            p.append('<rect x="%.1f" y=".5" width="35" height="35" rx="6" class="empty"/>' % (x + .5))
        p.append('<text x="%d" y="23" text-anchor="middle" class="hc num%s">%d</text>' % (x + 18, " on" if lvl >= 3 else "", c))
        p.append('<text x="%d" y="58" text-anchor="middle" class="tick">%d</text>' % (x + 18, 14 + i))
    p.append("</svg>")
    return "".join(p)


def throughput():
    v = ST["activity"]["probe_tok_s_last24"]
    x0, x1, yb, yt = 40, 552, 104, 10
    X = lambda i: x0 + i * (x1 - x0) / 23
    Y = lambda val: yb - val / 120 * (yb - yt)
    pts = " ".join("%.1f,%.1f" % (X(i), Y(a)) for i, a in enumerate(v))
    area = "M%.1f %d L%s L%.1f %dZ" % (X(0), yb, " L".join("%.1f %.1f" % (X(i), Y(a)) for i, a in enumerate(v)), X(23), yb)
    lo = v.index(min(v))
    return ('<svg class="chart" style="--s:1.2" viewBox="0 0 560 128" role="img" aria-labelledby="tp-t"><title id="tp-t">Probe throughput, last 24 checks: median 117.1, low %.1f, latest %.1f tok/s.</title>'
            '<line class="gl" x1="40" y1="%.1f" x2="552" y2="%.1f"/><text class="tick" x="32" y="%.1f" text-anchor="end">120</text>'
            '<line class="gl" x1="40" y1="%.1f" x2="552" y2="%.1f"/><text class="tick" x="32" y="%.1f" text-anchor="end">60</text>'
            '<line class="axis" x1="40" y1="%d" x2="552" y2="%d"/><text class="tick" x="32" y="%d" text-anchor="end">0</text>'
            '<path d="%s" class="area"/><polyline points="%s" class="line"/>'
            '<circle cx="%.1f" cy="%.1f" r="5" class="low"/><text class="ann" x="%.1f" y="%.1f">low %.1f</text>'
            '<circle cx="%.1f" cy="%.1f" r="5" class="now"/>'
            '<text class="tick" x="40" y="124">≈ −2 h</text><text class="tick" x="552" y="124" text-anchor="end">now</text></svg>') % (
        min(v), v[-1], Y(120), Y(120), Y(120) + 5, Y(60), Y(60), Y(60) + 5, yb, yb, yb + 5, area, pts,
        X(lo), Y(v[lo]), X(lo) + 12, Y(v[lo]) + 20, v[lo], X(23), Y(v[-1]))


def calls():
    rows = []
    for c in ST["calls"]:
        et = c.get("eval_tokens")
        if not c.get("ok", True):
            res = '<span class="chip chip-bad"><span class="g" aria-hidden="true">■</span>Failed %s</span>' % c.get("status", 502)
        elif c.get("no_usage") or et is None:
            res = '<span class="chip chip-warn"><span class="g" aria-hidden="true">▲</span>No usage</span>'
        else:
            res = '<span class="muted">ok</span>'
        out = '<span class="dash" aria-label="no count">—</span>' if et is None else n(et)
        rows.append('<tr><td class="num muted">%s</td><td><span class="mc">%s<span>%s</span></span></td><td class="id">%s</td><td class="r num">%s</td><td class="r num">%s</td><td>%s</td></tr>'
                    % (c["ts"][11:19], logo(c["model"], 16, "logo"), c["model"], c["agent"], n(c["prompt_tokens"]), out, res))
    return "".join(rows)


def evals():
    rows = []
    for r in ST["eval"]["per_model"]:
        dots = "".join('<span class="pd%s" aria-hidden="true"></span>' % ("" if i < r["passed"] else " miss") for i in range(r["total"]))
        verdict = '<span class="chip chip-bad"><span class="g" aria-hidden="true">■</span>Fail</span>' if r["verdict"] == "FAIL" else '<span class="muted">Pass</span>'
        rows.append('<li><span class="mc">%s<span>%s</span></span><span class="pds">%s<span class="num">%d/%d</span></span><span class="num muted">%.1f tok/s</span>%s</li>' % (
            logo(r["model"], 16, "logo"), r["model"], dots, r["passed"], r["total"], r["avg_tok_s"], verdict))
    return "".join(rows)


CSS = open(os.path.join(HERE, "round4b.css")).read()
ring_svg, ring_mb, ring_loaded = ring()
total_eval = M["eval_tokens_total"]

html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Lab status · Local AI Lab (round 4b mockup)</title>
<!-- Generated by mockups/build-mockup.py from tests/fixtures/status-metered.json. Static, zero-JS. -->
<style>""" + CSS + """</style>
</head>
<body>
""" + sprite() + """
<div class="shell">
<header class="top">
  <div class="brand">
    <span class="mark" aria-hidden="true"><svg width="22" height="22"><use href="#lg-ollama"/></svg></span>
    <span><b>Local AI Lab</b> <span class="scope">Mac Mini · 8 GB · tailnet</span></span>
  </div>
  <span class="chip chip-ok live"><span class="g pulse" aria-hidden="true">●</span>Operational</span>
  <span class="spacer"></span>
  <span class="stamp">Snapshot <time class="num" datetime="2026-10-27T11:00:00+00:00">11:00:00</time> UTC · probe 42 s ago</span>
  <a class="btn btn-primary" href="/agents.md">Agent guide</a>
</header>
<p class="notice">Mockup from a recorded fixture. Panels tagged <b>Sample</b> split the real totals with synthetic per-day and per-model data.</p>

<main class="grid">

  <section class="panel s12 kpis" aria-label="Headline numbers">
    <div class="kpi lead">
      <div class="kl">Tokens generated <span class="chip chip-measured">Measured</span></div>
      <div class="kv num">""" + n(total_eval) + """</div>
      <div class="ks"><span class="num">≈ """ + usd(COST["Base"]) + """</span> cloud cost avoided <span class="chip chip-est">Estimated</span></div>
    </div>
    <div class="kpi"><div class="kl">Prompt tokens</div><div class="kv num">""" + n(M["prompt_tokens_total"]) + """</div><div class="ks">measured input</div></div>
    <div class="kpi"><div class="kl">Calls</div><div class="kv num">""" + n(M["calls_total"]) + """</div><div class="ks"><span class="bad-t">1 failed</span> · 4 without usage</div></div>
    <div class="kpi"><div class="kl">Speed</div><div class="kv num">115.8<span class="u">tok/s</span></div><div class="ks">last probe · qwen2.5:0.5b</div></div>
    <div class="kpi declared"><div class="kl">Agent reports <span class="chip chip-declared">Self-declared</span></div><div class="kv num">445<span class="u">tok</span></div><div class="ks">7 reports · never added to the above</div></div>
  </section>

  <section class="panel s8" aria-labelledby="h-use">
    <div class="ph"><h2 id="h-use">Tokens by model</h2><span class="chip chip-sample">Sample</span><span class="meta">generated, per day, last 14 days</span></div>
    <div class="pb"><div class="wide-chart" role="region" aria-label="Tokens per day chart" tabindex="0">""" + stacked_chart() + "</div>" + leaderboard() + """</div>
  </section>

  <div class="s4 col">
    <section class="panel" aria-labelledby="h-cost">
      <div class="ph"><h2 id="h-cost">Cost avoided</h2><span class="chip chip-est">Estimated</span></div>
      <div class="pb">
        <div class="big num">""" + usd(COST["Base"]) + """</div>
        <div class="ks">if these """ + n(M["prompt_tokens_total"] + total_eval) + """ tokens had gone to a hosted API</div>
        """ + cost_range() + """
        <div class="legend"><span><i class="lg-rng"></i>range <span class="num">""" + usd(COST["Low"]) + " – " + usd(COST["High"]) + """</span></span><span><i class="lg-dot"></i>base</span></div>
        <details><summary>Assumed rates</summary>
          <table class="mini"><thead><tr><th></th><th class="r">in / 1M</th><th class="r">out / 1M</th><th class="r">total</th></tr></thead><tbody>"""
html += "".join('<tr><td>%s</td><td class="r num">$%.2f</td><td class="r num">$%.2f</td><td class="r num">%s</td></tr>' % (k, i, o, usd(COST[k])) for k, i, o in RATES)
html += """</tbody></table>
          <p class="fine">Reference rates, not quotes. Gross: electricity and hardware are not netted.</p>
        </details>
      </div>
    </section>
    <section class="panel ringp" aria-labelledby="h-ram">
      <div class="ph"><h2 id="h-ram">Memory in use</h2></div>
      <div class="pb ringrow">""" + ring_svg + """<div><div class="big2 num">""" + n(ring_mb) + """ MB</div><div class="ks"><span class="mc">""" + logo(ring_loaded[0]["name"], 16, "logo") + "<span>" + ring_loaded[0]["name"] + """</span></span> loaded</div><div class="ks">13 installed · 2 too big for this box</div></div></div>
      <div class="pb" style="padding-top:0">""" + ramfit() + """</div>
    </section>
  </div>

  <section class="panel s7" aria-labelledby="h-flow">
    <div class="ph"><h2 id="h-flow">Where tokens go</h2><span class="chip chip-sample">Sample</span><span class="meta">agent → proxy tap → model</span></div>
    <div class="pb"><div class="wide-chart" role="region" aria-label="Token flow diagram" tabindex="0">""" + sankey() + """</div><p class="fine">Agent names come from the X-Agent header: self-declared, not verified.</p></div>
  </section>

  <div class="s5 col">
    <section class="panel" aria-labelledby="h-tp">
      <div class="ph"><h2 id="h-tp">Throughput</h2><span class="meta">tok/s, last 24 probes</span><span class="end num big3">115.8</span></div>
      <div class="pb">""" + throughput() + """</div>
    </section>
    <section class="panel" aria-labelledby="h-act">
      <div class="ph"><h2 id="h-act">Activity</h2><span class="meta">probes per day</span><span class="end"><b class="num">8</b> <span class="muted">day streak</span></span></div>
      <div class="pb">""" + heat() + """</div>
    </section>
  </div>

  <section class="panel s8" aria-labelledby="h-calls">
    <div class="ph"><h2 id="h-calls">Recent calls</h2><span class="meta">5 of """ + n(M["calls_total"]) + """</span><a class="end" href="/calls">All calls</a></div>
    <div class="scroll" role="region" aria-labelledby="h-calls" tabindex="0"><table>
      <thead><tr><th>Time</th><th>Model</th><th>Agent <span class="chip chip-declared">Self-declared</span></th><th class="r">In</th><th class="r">Out</th><th>Result</th></tr></thead>
      <tbody>""" + calls() + """</tbody></table></div>
  </section>

  <section class="panel s4" aria-labelledby="h-eval">
    <div class="ph"><h2 id="h-eval">Weekly eval</h2><span class="meta num">2026-10-27</span></div>
    <ul class="evals">""" + evals() + """</ul>
  </section>

</main>
<nav class="links" aria-label="Endpoints">
  <a href="/status"><code>/status</code><span>live JSON</span></a>
  <a href="/calls"><code>/calls</code><span>metered ring</span></a>
  <a href="/agents.md"><code>/agents.md</code><span>agent guide</span></a>
  <a href="/api/tags"><code>/api/tags</code><span>models</span></a>
  <a href="/api/ps"><code>/api/ps</code><span>loaded now</span></a>
</nav>
<footer>Provider marks: lobehub/lobe-icons (MIT); trademarks of their owners. Zero JavaScript.</footer>
</div>
</body>
</html>
"""
open(os.path.join(HERE, "dashboard-round4b.html"), "w").write(html)
print("wrote mockups/dashboard-round4b.html")
