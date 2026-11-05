# Project Structure

This repository is now organized around the finalized Q1-Q3 solution and the safe Q4 solution.

## Final Solution Areas

- `FINAL_Q1_Q2/`: finalized Q1 and Q2 materials and supporting outputs.
- `strategies/a/`: Q1/A strategy implementation.
- `strategies/b/`: Q2/B strategy implementation.
- `strategies/c/`: Q3/C strategy implementation.
- `q3/`: Q3 active sensing, evaluation, and local testing infrastructure.
- `q4/`: Q4 base geometry, simulator, and controller infrastructure.
- `q4_stable/`: selected Q4 safe strategy. This is the current Q4 candidate for official use.
- `run_q4_stability_official.py`: official runner for the selected Q4 safe strategy.

## Fixed Inputs And Tests

- `cases/`: fixed local cases. Do not regenerate or overwrite these without documenting why.
- `test_*.py` and `tests/`: regression and unit tests.
- `requirements-official-simulator.txt`: dependency note for the official simulator interface.

## Evidence And Reports

- `Q4_STABILITY_AND_COMPLETENESS_REPORT.md`: main Q4 safe report.
- `Q4_COMPLETENESS_PROOF.md`: Q4 coverage/completeness proof notes.
- `Q4_SAFETY_AUDIT.md`: Q4 safe audit notes.
- `experiments/`: reproducible scripts, summaries, figures, and compact JSON evidence.
- `results/Q3_C_final/`: retained Q3 final run evidence.
- `results/Q3_C_route_v2/`: retained Q3 route comparison evidence.

## Archived Or Removed

The historical `.worktrees/` working directories were removed after Q1-Q3 were finalized and Q4 was returned to the safe strategy. They were multi-gigabyte development copies and are no longer needed for normal review or final execution.

Temporary audit and trial outputs were removed from `audit_temp/` and from obsolete `results/` subfolders. Python bytecode caches outside `.venv/` were also removed.

The Q4 aggressive branch was not selected for final use. It performed well in local holdout tests but official rehearsal showed non-full-clear outcomes, so the project decision is to use `q4_stable/` and `run_q4_stability_official.py`.

## Cleanup Policy

- Keep source code, fixed cases, tests, final reports, and compact experiment summaries.
- Keep final evidence needed to reproduce the selected Q1-Q4 decisions.
- Store large raw logs under `results/` only when they support a still-active decision.
- Remove temporary worktrees, `__pycache__/`, probe runs, smoke-test logs, and abandoned tuning outputs after their summaries have been preserved.
