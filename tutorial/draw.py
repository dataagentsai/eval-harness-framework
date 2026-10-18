"""Pictures of sessions: three lanes (customer, agent, tools), one row per step.

A step a check flagged is drawn hatched, with what the check said under the
picture. The picture is drawn from a real `Session`, so it shows exactly what
the check read.
"""

from html import escape

from kit import box, fig, path, text

LANES = {"user": 20, "assistant": 330, "decision": 330, "tool_call": 640, "tool_result": 640}
W, ROW, BH = 280, 88, 72


def _short(s, n=34):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _args(arguments):
    return ", ".join(f"{k}={v}" for k, v in arguments.items())


def _result(value):
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def _wrap(s, n=34, lines=2):
    words, out, cur = " ".join(str(s).split()).split(" "), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = _short(out[-1] + " …", n)
    return out


def label(step):
    """(title, sub-lines) for one step, in plain words."""
    if step.kind == "user":
        return "Customer", _wrap(f"“{step.text}”")
    if step.kind == "assistant":
        return "Agent says", _wrap(f"“{step.text}”")
    if step.kind == "decision":
        return "Agent decides", [step.name]
    if step.kind == "tool_call":
        return f"calls {step.name}", _wrap(_args(step.arguments) or "(no arguments)")
    if step.is_error:
        return f"{step.name} FAILED", _wrap(step.text or "error")
    return f"{step.name} returns", _wrap(_result(step.result))


def kind(step, flagged):
    if flagged:
        return "hatch"
    return {"user": "bx", "assistant": "bxs", "decision": "bxm",
            "tool_call": "solid", "tool_result": "bx"}[step.kind]


def session_figure(session, caption, flags=None, label_text="A session drawn as lanes"):
    """`flags`: {step index: what the check said}."""
    flags = flags or {}
    steps = session.steps
    h = 60 + ROW * len(steps) + (34 * len(flags) + 10 if flags else 0)
    body = [text(20 + W / 2, 28, "CUSTOMER", "lbl", "middle"),
            text(330 + W / 2, 28, "AGENT", "lbl", "middle"),
            text(640 + W / 2, 28, "TOOLS (its systems)", "lbl", "middle")]
    prev = None
    for i, s in enumerate(steps):
        x, y = LANES[s.kind], 44 + ROW * i
        title, sub = label(s)
        if i in flags:
            title = f"✗ {title}"
        drawn = box(x, y, W, BH, title, sub, kind=kind(s, i in flags))
        if i in flags:  # white halo so the words read over the hatching
            drawn = drawn.replace('class="tt"', 'class="tt lb"').replace('class="sm"', 'class="sm lb"')
        body.append(drawn)
        cx = x + W / 2
        if prev is not None:
            px, py = prev
            if px == cx:
                body.append(path(f"M{cx} {py + BH} L{cx} {y}"))
            else:
                body.append(path(f"M{px} {py + BH} L{px} {y + BH / 2} L{cx + (-W / 2 if cx > px else W / 2)} {y + BH / 2}"))
        prev = (cx, y)
    y = 44 + ROW * len(steps) + 16
    for i, said in flags.items():
        where = f"step {i + 1}" if i < len(steps) else "by the end"
        body.append(text(20, y, f"✗ {where}: {said}", "bd"))
        y += 34
    return fig(940, h, "".join(body), label_text, caption)


def result_card(result):
    """An EvalResult as the framework returned it, in a small table."""
    rows = [("verdict", f"<b>{result.verdict}</b>"),
            ("score", "—" if result.score is None else f"{result.score:.2f}"),
            ("reason", escape(result.reason)),
            ("evaluator", escape(result.evaluator)),
            ("provider", escape(result.provider))]
    if result.findings:
        rows.append(("findings", "<br>".join(escape(f"{f.kind}: {f.label}") for f in result.findings)))
    body = "".join(f"<tr><td><code>{k}</code></td><td>{v}</td></tr>" for k, v in rows)
    return f'<div class="tw"><table class="res">{body}</table></div>'


def flags_of(result):
    """{step index: label} from a pattern's raw answer, which keeps where each finding was."""
    return {f["step"]: f["label"] for f in result.raw.get("findings", ()) if "step" in f}
