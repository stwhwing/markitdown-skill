#!/usr/bin/env python3
"""content_detect.py — Decide whether extracted Markdown is real content.

Split out of ``url_to_markdown.py``: the heuristics that distinguish genuine
body prose from nav/footer/UI chrome. Kept separate because this is the logic
most likely to need tuning, and it should be reviewable without wading through
network/browser code.
"""
import re

TEXT_THRESHOLD = 120  # meaningful chars below which we treat the page as a likely SPA shell


def meaningful_len(text):
    """Length of text after stripping code, links and whitespace noise."""
    t = re.sub(r"```[\s\S]*?```", " ", text)
    t = re.sub(r"`[^`]*`", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\s+", "", t)
    return len(t)


# We measure VISIBLE text only — markdown image/link/URL lines (e.g.
# `![](https://...)`) are long but carry no body, so they are stripped before
# any check. The detector then distinguishes real body prose from nav/footer/UI
# chrome using sentence punctuation: real Chinese prose is full of CJK
# punctuation (，。、；：！？) spread across many sentences, whereas chrome is a
# handful of short isolated tokens (or one concatenated token line with no
# spaces, e.g. 首页番剧直播游戏中心...) and carries little or no punctuation.
# English pages are detected via a real English sentence.
_URL_RE = re.compile(r'https?://\S+')
_CJK_PUNCT = re.compile(r'[，。、；：！？]')
# A markdown line whose visible text is essentially a single link / image.
_LINK_LINE_RE = re.compile(r'^(!?\[|\s*\[)')


def _visible_line(ln):
    """Strip markdown image/link/code and bare URLs, leaving only visible text."""
    ln = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', ln)          # images
    ln = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', ln)      # links -> keep text
    ln = re.sub(r'`[^`]*`', '', ln)                       # inline code
    ln = _URL_RE.sub('', ln)                             # bare urls
    return ln


def is_real_content(md):
    """Heuristic: does `md` look like genuine body text (prose/paragraphs)
    rather than nav/footer/UI chrome?

    Returns True when the output looks like real prose. Two signals carry most
    of the weight, because either one alone is fooled:
      * paragraph mass — an article runs several sentences together into long
        lines, whereas a sidebar / index / UI page is entirely short items.
      * link density — a docs sidebar is mostly markdown link lines, while an
        article body has almost none.
    A loose "a handful of Latin words" test is deliberately NOT used: a Chinese
    docs page sprinkled with IDE / CLI / Menu / Sidebar Navigation clears it
    easily, which is exactly how a nav-only page used to pass as content.
    English is detected through a real English sentence, Chinese through body
    mass plus sentence punctuation.
    """
    if not md or not md.strip():
        return False
    lines = [ln.strip() for ln in md.splitlines()]
    vis = [" ".join(_visible_line(ln).split()) for ln in lines]
    vis = [v for v in vis if v]
    if not vis:
        return False
    text = " ".join(vis)

    # 1) paragraph mass — real prose has several long, sentence-bearing lines.
    long_lines = sum(1 for v in vis if len(v) >= 60)
    if long_lines >= 3:
        return True

    # 2) link density — sidebar / directory pages are dominated by link lines.
    nonempty = [ln for ln in lines if ln]
    if nonempty:
        link_lines = sum(1 for ln in nonempty if _LINK_LINE_RE.match(ln))
        if link_lines / len(nonempty) > 0.4:
            return False

    # 3) English paragraph
    if re.search(r'[A-Za-z]{12,}', text):
        return True

    # 4) Chinese prose: BOTH real body mass AND sentence punctuation.
    cjk_punct = len(_CJK_PUNCT.findall(text))
    if meaningful_len(md) >= 200 and cjk_punct >= 2:
        return True
    return False


def accept_content(md):
    """Combined gate: enough text AND it looks like real content (not boilerplate)."""
    return meaningful_len(md) >= TEXT_THRESHOLD and is_real_content(md)
