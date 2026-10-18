"""Drawing kit and page shell for the Eval Harness Tutorial.

Copied from ~/agent-harness-tutorial/kit.py so both tutorials look the same.

Same look as LearnLLMStack/finetune-path: Patrick Hand, black ink on white,
wobbly boxes (an SVG turbulence filter), cartoon arrows.

A box with href= is clickable and gets a small "look inside" tab, so a
diagram doubles as navigation: click a box to drill down one level.
"""
from html import escape

# ---------------------------------------------------------------- SVG kit

def _lines(x, y, lines, cls, gap, anchor="middle"):
    out = []
    for i, ln in enumerate(lines):
        out.append(f'<text class="{cls}" x="{x}" y="{y + i * gap}" text-anchor="{anchor}">{escape(ln)}</text>')
    return "".join(out)


def box(x, y, w, h, title, sub=(), kind="bx", href=None, tag="zoom in"):
    """A wobbly box. title/sub may be a str or a list of lines.
    kind: bx (plain) · bxs (grey) · bxm (dashed: optional / outside) · solid (dark, the star of the picture)."""
    title = [title] if isinstance(title, str) else list(title)
    sub = [sub] if isinstance(sub, str) else list(sub)
    inv = kind == "solid"
    tcls = "tt inv" if inv else "tt"
    scls = "inv sm2" if inv else "sm"
    th, sh = 24, 19
    total = len(title) * th + len(sub) * sh
    cy = y + h / 2 - total / 2 + 18
    cx = x + w / 2
    # pastel pencil: a soft fill laid slightly off the ink outline, like coloured pencil on a wireframe
    body = f'<rect class="pf pf-{kind}" x="{x + 4}" y="{y + 4}" width="{w - 2}" height="{h - 2}" rx="12"/>' if kind != "bxm" else ""
    body += f'<rect class="{kind} ol" x="{x}" y="{y}" width="{w}" height="{h}" rx="12"/>'
    body += _lines(cx, cy, title, tcls, th)
    body += _lines(cx, cy + len(title) * th, sub, scls, sh)
    if not href:
        return body
    tag += " ›"
    tw = 14 + 7.2 * len(tag)
    tx, ty = x + w - tw - 8, y - 13
    body += (f'<rect class="tag" x="{tx}" y="{ty}" width="{tw}" height="22" rx="11"/>'
             f'<text class="tagt" x="{tx + tw / 2}" y="{ty + 16}" text-anchor="middle">{escape(tag)}</text>')
    return f'<a class="lk" href="{href}"><title>Open: {escape(" ".join(title))}</title>{body}</a>'


def arrow(x1, y1, x2, y2, label=None, kind="ln", lx=None, ly=None, anchor="middle"):
    s = f'<line class="{kind}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" marker-end="url(#ar)"/>'
    if label:
        lx = (x1 + x2) / 2 if lx is None else lx
        ly = (y1 + y2) / 2 - 8 if ly is None else ly
        s += text(lx, ly, label, "sm", anchor)
    return s


def path(d, kind="ln", end=True):
    m = ' marker-end="url(#ar)"' if end else ""
    return f'<path class="{kind}" d="{d}"{m}/>'


def text(x, y, s, cls="tx", anchor="start"):
    lines = [s] if isinstance(s, str) else s
    return _lines(x, y, lines, cls, 20, anchor)


def num(x, y, n):
    """A small hand-drawn number in a circle, for numbered steps."""
    return (f'<circle class="nm" cx="{x}" cy="{y}" r="14"/>'
            f'<text class="nmt" x="{x}" y="{y + 6}" text-anchor="middle">{n}</text>')


def svg(w, h, body, label):
    return (f'<figure><div class="scroll"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}" '
            f'style="min-width:{min(w, 680)}px">{body}</svg></div>')


def fig(w, h, body, label, caption):
    return svg(w, h, body, label) + f'<figcaption>{caption}</figcaption></figure>'


def flow3(goes_in, happens, comes_out):
    return (f'<div class="flow3"><div><span>Goes in</span>{goes_in}</div>'
            f'<div><span>What happens</span>{happens}</div><div><span>Comes out</span>{comes_out}</div></div>')


def table(head, rows):
    h = "".join(f"<th>{c}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table><tr>{h}</tr>{b}</table></div>'


def note(title, body):
    return f'<div class="box"><b>{title}</b>{body}</div>'


# ---------------------------------------------------------------- page shell

CSS = r"""
:root{color-scheme:light;--bg:#FFFFFF;--paper:#FFFFFF;--ink:#222222;--muted:#5E5E5E;--line:#222222;--soft:#F3F3F1;--fill:#ECECEA;
--hand:"Patrick Hand","Comic Sans MS",cursive;--mono:"JetBrains Mono",ui-monospace,Menlo,monospace;
--wob:255px 18px 225px 18px/18px 225px 18px 255px;--side:290px}
*{box-sizing:border-box}
html{scroll-padding-top:120px}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--hand);font-size:20px;line-height:1.55}
a{color:var(--ink)}
/* top bar */
.top{position:sticky;top:0;z-index:20;background:var(--paper);border-bottom:2px solid var(--ink)}
.top .row{display:flex;align-items:center;gap:14px;padding:8px 16px;flex-wrap:wrap}
.home{font-size:15px;color:var(--muted);text-decoration:none;border-right:1.5px dotted #888;padding-right:12px}
.brand{font-size:24px;text-decoration:none;white-space:nowrap}
.tabs{display:flex;gap:6px;flex-wrap:wrap}
.tabs a{text-decoration:none;font-size:18px;padding:2px 14px;border:2px solid var(--ink);border-radius:var(--wob);background:var(--paper)}
.tabs a.on{background:var(--ink);color:var(--paper)}
.tabs a:hover{background:var(--soft)} .tabs a.on:hover{background:var(--ink)}
.menu{display:none;font:18px var(--hand);padding:2px 12px;border:2px solid var(--ink);border-radius:var(--wob);background:var(--paper);cursor:pointer}
.crumbs{padding:0 16px 8px;font-size:17px;color:var(--muted)}
.crumbs a{color:var(--muted)} .crumbs b{color:var(--ink);font-weight:400}
/* left panel */
.side{position:fixed;top:var(--toph,92px);bottom:0;left:0;width:var(--side);overflow-y:auto;border-right:2px dashed var(--ink);padding:14px 10px 40px 14px;background:var(--paper)}
.side h4{margin:14px 0 4px;font-weight:400;font-size:15px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.side ul{list-style:none;margin:0;padding:0}
.side ul ul{padding-left:16px;border-left:1.5px dotted #888;margin-left:6px}
.side li a{display:block;text-decoration:none;font-size:17px;line-height:1.3;padding:3px 8px;border-radius:var(--wob)}
.side li a:hover{background:var(--soft)}
.side li a.on{background:var(--ink);color:var(--paper)}
.side li a.path{text-decoration:underline;text-decoration-style:wavy;text-underline-offset:4px}
main{margin-left:var(--side)}
.wrap{max-width:980px;margin:0 auto;padding:22px 20px 60px}
@media (max-width:900px){.side{display:none;z-index:15;width:min(320px,90vw);box-shadow:4px 0 0 var(--ink)}.side.open{display:block}main{margin-left:0}.menu{display:inline-block}}
/* page */
.kicker{margin:0 0 4px;font-size:17px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
h1{font-size:clamp(32px,5.5vw,46px);font-weight:400;margin:0 0 6px;line-height:1.1}
h3{font-size:24px;font-weight:400;margin:22px 0 6px}
h2{font-size:clamp(26px,4vw,32px);font-weight:400;margin:28px 0 8px;line-height:1.15}
.lede{margin:0 0 14px;color:var(--muted);max-width:75ch}
.page{display:grid;gap:18px}
.flow3{display:grid;grid-template-columns:1fr 1.4fr 1fr;gap:10px}
.flow3 div{background:var(--paper);border:2px solid var(--ink);border-radius:var(--wob);padding:10px 14px;font-size:18px;line-height:1.35}
.flow3 div:nth-child(2){background:var(--soft)}
.flow3 span{display:block;font-size:15px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-bottom:2px}
@media (max-width:640px){.flow3{grid-template-columns:1fr}}
figure{margin:0;background:var(--paper);border:2px solid var(--ink);border-radius:var(--wob);padding:16px}
figcaption{font-size:17px;color:var(--muted);margin-top:8px}
.scroll{overflow-x:auto}
figure svg{display:block;width:100%;height:auto}
.text p{margin:0 0 10px;max-width:74ch}
.text ol,.text ul{margin:0 0 10px;padding-left:24px;max-width:74ch}
.text li{margin-bottom:6px}
table{border-collapse:collapse;margin:6px 0 14px;background:var(--paper);border:2px solid var(--ink);font-size:18px;width:100%}
th,td{text-align:left;padding:6px 10px;border-bottom:1px dashed #999;vertical-align:top}
th{font-size:15px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--ink);font-weight:400}
.tw{overflow-x:auto}
code{font-family:var(--mono);font-size:.74em;background:var(--soft);padding:1px 5px;border-radius:4px}
pre{margin:0 0 12px;background:var(--soft);border:2px solid var(--ink);border-radius:var(--wob);padding:12px 16px;overflow-x:auto;font:500 14px/1.55 var(--mono)}
pre .c{color:var(--muted)}
.box{background:var(--soft);border:2px dashed var(--ink);border-radius:var(--wob);padding:12px 16px;margin:0 0 12px;max-width:74ch}
.box>b:first-child{display:block;font-size:15px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:400;margin-bottom:2px}
.inside{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.inside a{display:block;text-decoration:none;border:2px solid var(--ink);border-radius:var(--wob);padding:10px 14px;background:var(--paper)}
.inside a:hover{background:var(--soft)}
.inside b{display:block;font-weight:400;font-size:21px}
.inside span{color:var(--muted);font-size:17px;line-height:1.3;display:block}
.pn{display:flex;justify-content:space-between;gap:10px;margin-top:30px;border-top:2px solid var(--ink);padding-top:14px}
.pn a{text-decoration:none;font-size:19px;padding:6px 16px;border:2px solid var(--ink);border-radius:var(--wob);max-width:48%}
.pn a.nx{background:var(--ink);color:var(--paper);margin-left:auto;text-align:right}
.pn small{display:block;font-size:14px;letter-spacing:.06em;text-transform:uppercase;opacity:.75}
.deeper{font-size:17px;color:var(--muted)}
.snip{border:2px solid var(--ink);border-radius:var(--wob);margin:0 0 14px;background:var(--soft);overflow:hidden}
.snip-h{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:baseline;padding:8px 16px;border-bottom:1.5px dashed var(--ink);background:var(--paper)}
.snip-h span{font-size:17px}
.snip pre,pre,code{font-variant-ligatures:none;font-feature-settings:"liga" 0,"calt" 0}
.snip pre{margin:0;border:0;border-radius:0;max-height:520px;overflow:auto;font-size:13px}
/* svg */
figure svg rect,figure svg line,figure svg path,figure svg polyline,figure svg circle,figure svg ellipse{filter:url(#rough)}
svg text{font-family:var(--hand)}
.bx{fill:#EAF3FB;stroke:var(--ink);stroke-width:2}
.bxm{fill:#FFFFFF;stroke:var(--ink);stroke-width:2;stroke-dasharray:7 5}
.bxs{fill:#FFF3C9;stroke:var(--ink);stroke-width:2}
.solid{fill:#E4D9F6;stroke:var(--ink);stroke-width:2.4}
.ol{fill:transparent}
.pf{stroke:none;opacity:.95} .pf-bx{fill:#D3E6F7} .pf-bxs{fill:#FFE59A} .pf-solid{fill:#D5C6F1} .pf-hatch{fill:#F6CFC8}
.zone{fill:none;stroke:var(--ink);stroke-width:1.8;stroke-dasharray:3 6}
.hatch{fill:url(#hatch);stroke:var(--ink);stroke-width:1.8}
.zg{fill:#DCF1D2;stroke:none}.zy{fill:#FBF1BE;stroke:none}.zr{fill:#F7CFCA;stroke:none}
.hz{fill:#fff;stroke:var(--ink);stroke-width:2.2;stroke-linejoin:round;stroke-linecap:round}
.hk{fill:var(--ink);stroke:var(--ink);stroke-width:1.5}
.swg{display:inline-block;width:14px;height:14px;border:1.5px solid #222;border-radius:3px;vertical-align:-2px;margin-right:4px}
.tx{fill:var(--ink);font-size:17px}
.tt{fill:var(--ink);font-size:20px}
.sm{fill:var(--muted);font-size:15px}
.lb{paint-order:stroke;stroke:#fff;stroke-width:5px;stroke-linejoin:round}
.sm2{font-size:15px}
.bd{fill:var(--ink);font-size:18px}
.lbl{fill:var(--muted);font-size:15px;letter-spacing:.06em}
.inv{fill:var(--ink)}
.mn{font-family:var(--mono);font-size:12.5px;fill:var(--ink)}
.ln{stroke:var(--ink);stroke-width:1.8;fill:none}
.lnd{stroke:var(--ink);stroke-width:1.8;fill:none;stroke-dasharray:6 5}
.lnc{stroke:var(--ink);stroke-width:3;fill:none;stroke-linecap:round}
.nm{fill:var(--paper);stroke:var(--ink);stroke-width:2}
.nmt{fill:var(--ink);font-size:16px}
.tag{fill:var(--paper);stroke:var(--ink);stroke-width:1.5;stroke-dasharray:3 3}
.tagt{fill:var(--ink);font-size:13.5px}
a.lk{cursor:pointer}
a.lk:hover .pf{opacity:1;filter:url(#rough) saturate(1.5)}
a.lk:hover .bxm{fill:#F3F3F1}
a.lk:hover .ol{stroke-width:3}
a.lk:hover .tag{fill:var(--ink)} a.lk:hover .tagt{fill:#fff}
a.lk:focus-visible rect{stroke-width:4}
"""

DEFS = """<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<filter id="rough" filterUnits="userSpaceOnUse" x="-50" y="-50" width="2200" height="2600"><feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="4"/><feDisplacementMap in="SourceGraphic" scale="2.4"/></filter>
<pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="7" style="stroke:#222;stroke-width:1.4"/></pattern>
<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" style="fill:#222"/></marker>
</defs></svg>"""

JS = r"""
(function(){
  var top=document.querySelector('.top'),side=document.querySelector('.side');
  function fit(){document.documentElement.style.setProperty('--toph',top.offsetHeight+'px')}
  fit();window.addEventListener('resize',fit);
  var m=document.querySelector('.menu');if(m)m.onclick=function(){side.classList.toggle('open')};
  var on=side.querySelector('a.on');if(on)on.scrollIntoView({block:'center'});
  document.addEventListener('keydown',function(e){
    if(e.target.tagName==='INPUT')return;
    var a=e.key==='ArrowRight'?document.querySelector('.pn .nx'):e.key==='ArrowLeft'?document.querySelector('.pn .pv'):null;
    if(a)location.href=a.getAttribute('href');
  });
})();
"""
