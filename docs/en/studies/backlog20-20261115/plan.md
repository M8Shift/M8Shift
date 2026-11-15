# Batch implementation plan

Baseline: public candidate `3e3b070a667a6c978de0affab5bc48ec853b7549`. Private source revisions may be inspected and selected behavior ported without importing ancestry. Keep the newer public Python policy, advisory routing, session lookup and deterministic tests.

1. Restore listener instance environment construction inside the actual loop. The detached launcher generates its own generation; remove the unused misplaced construction from the startup dispatcher.
2. Extend behavioral tests across full loop/liveness paths. Preserve legacy direct-call behavior and verify bound-instance propagation.
3. Compare private main by function for integrity, quota liveness/advice and operational diagnostics; port only applicable source/test contracts and update manifests.
4. Inspect remaining original issue criteria against actual candidate behavior, add missing bounded diagnostics or document exact residual scope. Retain explicit provider and live-fleet acceptance gaps.
5. Keep portability/publication evidence scoped. Validate new code with disposable instances; never use the live coordinating relay to test recovery.
6. Finish with a twenty-item criterion/evidence matrix and common project checkpoint. Native cockpit implementation stays in the separate UI repository.
