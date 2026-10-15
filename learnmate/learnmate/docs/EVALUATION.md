# Evaluation report

**What this measures:** the offline *demo mode* (keyword search + extracted sentences, no AI service) on the shipped demo course (8 x 30 s lecture on Python lists, 4-page PDF, 6 slides), using 20 hand-written questions. Re-create with `python evaluation/run_eval.py`.

**What this does NOT measure:** answer quality with a real AI model (no API key / network was available when this was written), other courses, other languages, or real learners. Treat the numbers as a regression check of our logic, not as proof of accuracy.

## Results

| Metric | Result |
|---|---|
| Questions that should be answered were answered | 11/11 (100%) |
| Citation correctness (a shown source contains the expected fact) | 11/11 (100%) |
| Refusal correctness (not in content / not yet watched -> 'not found') | 9/9 (100%) |
| Later-content leaks (a source later than the playhead, or later-only words in a source) | 0 of 20 |
| Average / worst response time (local, demo mode, no network) | 0.3 ms / 0.6 ms |

## Every case

| Type | Question | Playhead | Expected | Got | Citation ok | Leak |
|---|---|---|---|---|---|---|
| before/after timestamp | How do I add an item to a list? | 40s | not_found | not_found | - | no |
| before/after timestamp | How do I add an item to a list? | 100s | found | found | yes | no |
| before/after timestamp | What does pop do? | 100s | not_found | not_found | - | no |
| before/after timestamp | What does pop do? | 150s | found | found | yes | no |
| before/after timestamp | How does slicing work? | 100s | not_found | not_found | - | no |
| before/after timestamp | How does slicing work? | 200s | found | found | yes | no |
| before/after timestamp | What is negative indexing? | 20s | not_found | not_found | - | no |
| before/after timestamp | What is negative indexing? | 70s | found | found | yes | no |
| before/after timestamp | What is a list comprehension? | 150s | not_found | not_found | - | no |
| before/after timestamp | What is a list comprehension? | 240s | found | found | yes | no |
| PDF / slide answer | What are the arguments of insert? | 240s | found | found | yes | no |
| PDF / slide answer | How do I loop over a list with for? | 240s | found | found | yes | no |
| PDF / slide answer | What does remove do compared to pop? | 240s | found | found | yes | no |
| not in the content | What is a dictionary? | 240s | not_found | not_found | - | no |
| not in the content | How do I sort a list? | 240s | not_found | not_found | - | no |
| not in the content | Who invented Python? | 240s | not_found | not_found | - | no |
| not in the content | What is a tuple? | 240s | not_found | not_found | - | no |
| follow-up | and how do I use it? | 100s | found | found | yes | no |
| follow-up | what about at the front? | 130s | found | found | yes | no |
| follow-up | and does it return anything? | 160s | found | found | yes | no |

## What the first run found

The first run answered only 8 of 11 answerable questions: generic words such as 'over', 'compared' and 'anything' were treated as required keywords. They were added to the stop-word list in `search.py` (not special-cased per question) and the run was repeated. A second finding was a too-narrow expectation: the loop question was answered correctly from the 'loop variable' sentence, so that phrase was added to the accepted evidence for that case.

## Known limits (found while testing)

- Keyword search cannot match synonyms (a question that says 'delete' will not find text that says 'remove'). The AI model does not fix this, because it only sees what the search returns.
- 'What did he mean here?' is only answerable in live mode (the offline demo has no language understanding).
- Page unlock times for PDF/slides are set by hand in `demo_course/mapping.json`; a wrong table means a page unlocks too early or late.
- Interview scores are word-matching, so a correct answer in different words can score low.
- Video chunks unlock when they start, but text is cut at the playhead line by line, so a line that has not started yet is never used.

## Still to do before claiming more

- Run the same questions with a real AI key and record answer quality by hand.
- Try 3-5 real learners on a real lecture and note where 'not found' is wrong.
