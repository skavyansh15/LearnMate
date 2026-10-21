"""Tiny keyword search (BM25). No vector database, no embeddings, no downloads."""
import math
import re
from collections import Counter

STOP = set("""a an the is are was were be been being of to in on for and or it its this that these those with as at by
from what why how when who whom which does do did can could would should will i you he she we they his her their our
about into than then so if not no yes my me your there here where also just very more most some any each
work works use used using explain tell show give get make example examples difference between mean means meaning define describe please over compare compared comparing anything something thing things way ways
video videos lecture lectures lecturer instructor teacher speaker course lesson class material materials covered cover covers
watched watch watching far said say says talk talks taught teach teaches""".split())


def stem(w):
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)]
            break
    if w.endswith("e") and len(w) > 3:
        w = w[:-1]
    return w


def words(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and (len(w) > 1 or w.isdigit())]


def tokens(text):
    return [stem(w) for w in words(text)]


def search(chunks, query, k=4, min_coverage=0.6):
    """Best chunks for the query. A chunk must contain at least half of the question's key words
    (rare words count more). If nothing qualifies there is NO evidence, which is what makes 'not found' possible."""
    q = set(tokens(query))
    if not q or not chunks:
        return []
    docs = [Counter(tokens(c["text"])) for c in chunks]
    n = len(docs)
    avgdl = (sum(sum(d.values()) for d in docs) / n) or 1
    df = Counter(t for d in docs for t in d)
    idf = {t: math.log(1 + (n + 1) / (df[t] + 1)) for t in q}  # a word nobody uses gets the highest weight
    total = sum(idf.values())
    scored = []
    for c, d in zip(chunks, docs):
        matched = [t for t in q if t in d]
        if not matched or sum(idf[t] for t in matched) / total < min_coverage:
            continue
        dl = sum(d.values())
        score = sum(idf[t] * d[t] * 2.2 / (d[t] + 1.2 * (0.25 + 0.75 * dl / avgdl)) for t in matched)
        scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:k]]


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def top_terms(texts, k=10):
    """Most characteristic words of a set of texts (readable form, e.g. 'append', not 'append')."""
    tf, df, surface = Counter(), Counter(), {}
    for text in texts:
        seen = set()
        for w in words(text):
            if len(w) < 4 or w.isdigit():
                continue
            s = stem(w)
            tf[s] += 1
            seen.add(s)
            if s not in surface or len(w) < len(surface[s]):
                surface[s] = w
        df.update(seen)
    n = len(texts) or 1
    ranked = sorted(tf, key=lambda s: -tf[s] * math.log(1 + n / df[s]))
    return [surface[s] for s in ranked[:k]]


def lead(text):
    """First real sentence (at least 5 words), skipping slide / page titles."""
    for sent in sentences(text):
        if len(sent.split()) >= 5:
            return sent
    return text[:160]


def best_sentence(text, query):
    """The sentence of `text` that shares the most words with `query` (falls back to the lead sentence)."""
    q = set(tokens(query))
    ranked = sorted(((len(q & set(tokens(s))), s) for s in sentences(text) if len(s.split()) >= 4), key=lambda x: -x[0])
    return ranked[0][1] if ranked and ranked[0][0] else lead(text)


def excerpt(text, query, size=220):
    """Short preview that STARTS at the sentence matching the question best, so the learner sees the cited fact."""
    sents = sentences(text)
    q = set(tokens(query))
    best = max(range(len(sents)), key=lambda i: (len(q & set(tokens(sents[i]))), -i)) if sents else 0
    out = ""
    for sent in sents[best:]:
        if out and len(out) + len(sent) > size:
            break
        out += sent + " "
    return out.strip()[:size] or text[:size]
