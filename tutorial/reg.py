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
    """A 'Your review' box: what I need you to tell me about this page."""
    if not any(r[0] == pid and r[1] == title for r in REVIEWS):
        REVIEWS.append((pid, title, list(questions)))
    items = "".join(f"<li>{q}</li>" for q in questions)
    return (f'<div class="review"><b>Your review · {title}</b>'
            f'<ol>{items}</ol><p class="deeper">Reply in chat with the page name and the number, '
            f'for example “session 2: …”.</p></div>')


def status(built, words=""):
    """A small label: built, or not built yet."""
    cls, label = ("st-ok", "Built") if built else ("st-no", "Not built yet")
    return f'<span class="st {cls}">{label}</span>{" " + words if words else ""}'
