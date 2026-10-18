"""Your review: every open question in the tutorial, in reading order."""

from reg import PAGES, REVIEWS, link, page


@page("review", "Everything I need your opinion on", None,
      "Every review question in the tutorial, in one list.", short="Your review")
def review_page():
    if not REVIEWS:
        return "<p>No open questions.</p>"
    order = {pid: PAGES[pid]["order"] for pid in PAGES}
    blocks = []
    for pid, title, questions in sorted(REVIEWS, key=lambda r: order.get(r[0], 0)):
        items = "".join(f"<li>{q}</li>" for q in questions)
        blocks.append(f'<div class="review"><b>{link(pid, title)}</b><ol>{items}</ol></div>')
    total = sum(len(r[2]) for r in REVIEWS)
    return f"""
<div class="text"><p>{total} questions across {len(REVIEWS)} pages. Read the page first; each
question links back to it. Answer in chat with the page name and the number,
for example “session 2: yes, add times”. Short answers are fine. Skip any
you don't have a view on.</p></div>
{''.join(blocks)}
"""
