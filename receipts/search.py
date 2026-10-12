"""Transparent, local interview retrieval. No embeddings or generated answers."""

import re

STOP_WORDS = set("a an the i me my you your we our us they their it its this that to of in on at with for from and or but so as is was were are be been being have has had do did does can could would should tell about time when how what which example examples give describe demonstrate demonstrated experience question please show find relevant evidence handled handle".split())
TOPICS = (
    ("coach coached coaching mentor mentored mentoring develop developed developing development junior juniors grow growth talent potential promotion promoted",),
    ("retain retaining retention retained redeploy redeployed mobility transition succession",),
    ("conflict disagreement difficult challenging feedback performance pip",),
    ("cost costs saving savings efficiency budget commercial vendor expensive spend expenditure roi",),
    ("incident outage reliability production recovery crisis failure failed rollback",),
    ("change transformation restructure restructuring redundancy redundancies consultation uncertainty morale",),
    ("stakeholder stakeholders communicate communication messaging presentation influence alignment",),
    ("security devsecops vulnerability vulnerabilities risk",),
    ("architecture migration migrations platform technical scalability scaling",),
)


def query_terms(query, expand=False):
    words = list(dict.fromkeys(w for w in re.findall(r"[^\W_]+",query.lower(),re.UNICODE)
                               if len(w)>1 and w not in STOP_WORDS))[:24]
    if expand:
        original = set(words)
        for (group,) in TOPICS:
            terms = group.split()
            if original.intersection(terms):
                words.extend(t for t in terms if t not in words)
    return words[:80]
