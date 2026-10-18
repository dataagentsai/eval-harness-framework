"""Your review: every open question in the tutorial, in reading order."""

from reg import PAGES, REVIEWS, link, page, review_box


@page("review", "Questions and decisions", None,
      "Every review question in the tutorial and what was decided, in one list.", short="Your review")
def review_page():
    if not REVIEWS:
        return "<p>No open questions.</p>"
    order = {pid: PAGES[pid]["order"] for pid in PAGES}
    blocks = [review_box(title, questions, heading=link(pid, title))
              for pid, title, questions in sorted(REVIEWS, key=lambda r: order.get(r[0], 0))]
    total = sum(len(r[2]) for r in REVIEWS)
    open_ = sum(1 for r in REVIEWS for q in r[2] if not isinstance(q, tuple))
    status = (f"{open_} of {total} questions are open." if open_
              else f"All {total} questions are decided (you accepted my recommendations on 18 and 19 Oct 2026).")
    return f"""
<div class="text"><p>{status} Each links back to the page that explains it.
Open questions are answered in chat with the page name and the number, for
example “session 2: yes, add times”. To change a decision, say so the same way.</p></div>
{''.join(blocks)}
"""
