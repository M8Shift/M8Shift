# fix-and-review

`palindrome.py` ships ONE known bug; `test_palindrome.py` is the pinned oracle
(do not edit the test). Agent A runs the test (one case fails), fixes
`palindrome.py`, and appends the diff; agent B re-runs the test and approves
only on green. Deterministic: the test is the judge, whoever the agents are.
Run the oracle from this directory: `python3 -m pytest test_palindrome.py -q`
(or `python3 test_palindrome.py`). ~4-6 turns.
