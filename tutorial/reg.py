"""Page registry: pages register with @page; the parent links make the tree.

`review(...)` both renders a "Your review" box and records its questions, so
the Review page lists every open question in the tutorial without copying.
"""

PAGES = {}
REVIEWS = []  # (page id, title, [questions])


def page(pid, title, parent=None, blurb="", short=None):
    def deco(fn):
        PAGES[pid] = dict(id=pid, title=title, parent=parent, blurb=blurb,
                          short=short or title, render=fn, order=len(PAGES))
        return fn
    return deco


def href(pid):
    return f"{pid}.html"


def link(pid, text=None):
    """Link to another tutorial page by id (checked at build time)."""
    return f'<a href="{href(pid)}">{text or PAGES.get(pid, {}).get("short", pid)}</a>'


def review(pid, title, questions):
    """A 'Your review' box: what I need you to tell me about this page. A
    question may be a (question, decision) pair once you've answered it."""
    if not any(r[0] == pid and r[1] == title for r in REVIEWS):
        REVIEWS.append((pid, title, list(questions)))
    return review_box(title, questions)


def review_box(title, questions, heading=None):
    items = "".join(_item(q) for q in questions)
    open_ = sum(1 for q in questions if not isinstance(q, tuple))
    tail = ('<p class="deeper">Reply in chat with the page name and the number, '
            'for example “session 2: …”.</p>') if open_ else ""
    label = "Your review" if open_ else "Decided"
    return (f'<div class="review"><b>{heading or f"{label} · {title}"}</b>'
            f'<ol>{items}</ol>{tail}</div>')


def _item(q):
    if isinstance(q, tuple):
        question, decision = q
        return f'<li>{question}<br><span class="dec">Decided: {decision}</span></li>'
    return f"<li>{q}</li>"


def status(built, words=""):
    """A small label: built, or not built yet."""
    cls, label = ("st-ok", "Built") if built else ("st-no", "Not built yet")
    return f'<span class="st {cls}">{label}</span>{" " + words if words else ""}'
