"""Build the Eval Harness Tutorial into tutorial/site/*.html.

    .venv/bin/python tutorial/build.py
    .venv/bin/python tutorial/build.py --publish ~/cleandataengineering-site/learn/eval-harness

Pages register themselves with @page(...) in pages_*.py. The tree of parents
gives the left panel, the breadcrumb, the top tabs and the back/next order.
The examples on the pages are produced by running evalharness itself (live.py),
so they are what the code does today. Same kit and look as the Agent Harness
Tutorial (~/agent-harness-tutorial).
"""

import importlib
import re
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import kit  # noqa: E402
import live  # noqa: E402
from reg import PAGES, href  # noqa: E402

OUT = Path(__file__).parent / "site"
PUBLISH = "--publish" in sys.argv
"""`--publish DIR`: write the site there (cleandataengineering.ai's repo) with a home link."""
HOME = '<a class="home" href="https://cleandataengineering.ai/">cleandataengineering.ai</a>'
if PUBLISH:
    OUT = Path(sys.argv[sys.argv.index("--publish") + 1]).expanduser()
SECTIONS = ["pages_start", "pages_arch", "pages_hooks", "pages_outputs", "pages_session", "pages_patterns",
            "pages_yaml", "pages_traces", "pages_catalog", "pages_requirements", "pages_design",
            "pages_review"]

EXTRA_CSS = r"""
.review{background:#FFF8E1;border:2.5px solid var(--ink);border-radius:var(--wob);padding:12px 18px;margin:8px 0 12px;max-width:80ch}
.review>b:first-child{display:block;font-size:15px;letter-spacing:.06em;text-transform:uppercase;font-weight:400;margin-bottom:4px}
.review ol{margin:0 0 6px;padding-left:24px}.review li{margin-bottom:10px}
.dec{display:inline-block;margin-top:4px;padding:2px 10px;background:#DCF1D2;border:1.5px solid var(--ink);border-radius:var(--wob)}
.st{display:inline-block;font-size:14px;letter-spacing:.05em;text-transform:uppercase;padding:0 10px;border:1.5px solid var(--ink);border-radius:var(--wob)}
.st-ok{background:#DCF1D2}.st-no{background:#fff;border-style:dashed}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media (max-width:900px){.pair{grid-template-columns:1fr}}
.pair>div>h3{margin-top:0}
table.res td:first-child{white-space:nowrap;width:1%}
"""

TABS = [("index", "Start"), ("arch", "Architecture"), ("session", "Sessions"), ("patterns", "Five patterns"),
        ("yaml", "Writing rules"), ("traces", "From traces"), ("catalog", "Catalog"),
        ("requirements", "Requirements"), ("design", "Design"), ("review", "Your review")]


def children(pid):
    return sorted((p for p in PAGES.values() if p["parent"] == pid), key=lambda p: p["order"])


def ancestors(pid):
    out = []
    while pid:
        out.append(pid)
        pid = PAGES[pid]["parent"]
    return out[::-1]


def walk(pid=None):
    for c in children(pid):
        yield c["id"]
        yield from walk(c["id"])


def inside(pid):
    cs = children(pid)
    if not cs:
        return ""
    cards = "".join(f'<a href="{href(c["id"])}"><b>{c["title"]}</b><span>{c["blurb"]}</span></a>' for c in cs)
    return f'<h2>Look inside</h2><div class="inside">{cards}</div>'


def nav_tree(cur, pid=None):
    cs = children(pid)
    if not cs:
        return ""
    path = set(ancestors(cur))
    items = []
    for c in cs:
        cls = "on" if c["id"] == cur else ("path" if c["id"] in path else "")
        items.append(f'<li><a class="{cls}" href="{href(c["id"])}">{c["short"]}</a>{nav_tree(cur, c["id"])}</li>')
    return "<ul>" + "".join(items) + "</ul>"


def side(cur):
    out = []
    for top in children(None):
        out.append(f'<h4>{top["short"]}</h4>')
        out.append(f'<ul><li><a class="{"on" if top["id"] == cur else ""}" href="{href(top["id"])}">'
                   f'{"Overview" if children(top["id"]) else top["short"]}</a></li></ul>')
        out.append(nav_tree(cur, top["id"]))
    return "".join(out)


def tabs(cur):
    chain = ancestors(cur)
    ids = [t for t, _ in TABS]
    hit = next((a for a in reversed(chain) if a in ids), None)
    return "".join(f'<a class="{"on" if t == hit else ""}" href="{href(t)}">{n}</a>' for t, n in TABS)


def crumbs(cur):
    chain = ancestors(cur)
    parts = [f'<a href="{href(a)}">{PAGES[a]["short"]}</a>' for a in chain[:-1]]
    return "You are here: " + " › ".join(parts + [f'<b>{PAGES[cur]["short"]}</b>'])


def pn(cur, order):
    i = order.index(cur)
    s = ""
    if i > 0:
        p = PAGES[order[i - 1]]
        s += f'<a class="pv" href="{href(p["id"])}"><small>← Back</small>{p["short"]}</a>'
    if i < len(order) - 1:
        n = PAGES[order[i + 1]]
        s += f'<a class="nx" href="{href(n["id"])}"><small>Next →</small>{n["short"]}</a>'
    return f'<nav class="pn">{s}</nav>'


def render(pid, order):
    p = PAGES[pid]
    body = p["render"]()
    top = PAGES[ancestors(pid)[0]]["short"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(re.sub('<[^>]+>', '', p['short']))} · Eval Harness Tutorial</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Patrick+Hand&family=JetBrains+Mono:wght@500;700&display=swap">
<link rel="stylesheet" href="style.css"></head><body>
{kit.DEFS}
<header class="top"><div class="row"><button class="menu" aria-label="Show the page list">☰ Pages</button>
{HOME if PUBLISH else ""}<a class="brand" href="index.html">Eval Harness, drawn simply</a><nav class="tabs" aria-label="Sections">{tabs(pid)}</nav></div>
<div class="crumbs">{crumbs(pid)}</div></header>
<aside class="side" aria-label="All pages">{side(pid)}</aside>
<main><div class="wrap"><article class="page">
<header><p class="kicker">Eval Harness Tutorial · {top}</p><h1>{p['title']}</h1></header>
{body}
{inside(pid)}
</article>{pn(pid, order)}</div></main>
<script src="nav.js"></script></body></html>"""


def main():
    # Importing a pages module registers its pages; this list is the reading order.
    for name in SECTIONS:
        importlib.import_module(name)

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.html"):
        old.unlink()
    order = list(walk())
    (OUT / "style.css").write_text(kit.CSS + EXTRA_CSS)
    (OUT / "nav.js").write_text(kit.JS)
    # Render every page once first, so every review box is registered before
    # the Review page (last in the tree) lists them.
    html = {pid: render(pid, order) for pid in order}
    html["review"] = render("review", order)
    for pid, text in html.items():
        (OUT / href(pid)).write_text(text)
    bad = [(f.name, h) for f in OUT.glob("*.html")
           for h in re.findall(r'href="([a-z0-9-]+)\.html"', f.read_text()) if h not in PAGES]
    assert not bad, bad
    if live.MISSING:
        print("code not found:", *live.MISSING, sep="\n  ")
    print(f"{len(order)} pages -> {OUT}")


if __name__ == "__main__":
    main()
