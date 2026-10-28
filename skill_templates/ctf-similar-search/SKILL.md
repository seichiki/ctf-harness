---
name: ctf-similar-search
description: Research public similar CTF challenges with Codex web search only when this run enables similar-search.
---
# Similar challenge research

This project adapter uses the search method of ljagiello/ctf-skills at revision
`2388a3bcd5f081836c9a038c54e26bc658d5b7d1`. The original reference
text and MIT notice are retained under `third_party/ctf-skills/`.

Use Codex web search for public writeups and techniques. Start with a short
query based on the challenge name or a distinctive non-secret clue. Open a
promising source before relying on it. Do not send a private challenge bundle,
credentials, or answer file to search. Do not request a Tavily key, install
packages, or run bundled upstream scripts.

Record each URL actually used and its contribution in the evidence report.
Label a candidate that relies on a public solution as reference-assisted.
A matching public flag is not proof that the present challenge has that answer.
Do not contact a live challenge target unless this run explicitly authorizes it.
