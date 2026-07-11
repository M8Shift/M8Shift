# Keep pytest discovery out of the shift demos (#102): their pinned oracle
# files are deliberately named test_*.py for the exercises themselves, and one
# demo intentionally starts unimplemented — collecting them would break the
# repo suite. The repo test class TestShiftDemos runs them as subprocesses.
collect_ignore_glob = ["examples/shift-demos/*"]
