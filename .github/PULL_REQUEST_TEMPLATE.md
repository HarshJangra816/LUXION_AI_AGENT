<!--
Thanks for contributing to Luxion! Please fill this in — it makes review much
faster. See CONTRIBUTING.md for the full guide.
-->

## What does this change?

<!-- What problem does this solve, and what did you change to solve it? -->

## How was it tested?

<!-- Which cases did you cover, and how did you verify them? -->

## Checklist

- [ ] `pytest` passes (backend)
- [ ] `ruff check .` and `ruff format --check .` pass (backend)
- [ ] `npm run lint` (oxlint) and `npm run build` (tsc + vite) pass (frontend)
- [ ] `cargo check` passes (Tauri shell, if `src-tauri/` was touched)
- [ ] `memory.md` is updated in this PR
- [ ] No secrets, `.env` files, `database/*.json` or local artefacts are committed
- [ ] New behaviour has tests in `backend/tests/`

## Dependencies

- [ ] No new Python dependency
- [ ] New dependency added — justified below

<!--
If you added a dependency, explain what the standard library cannot do and why
the licence is acceptable. Phases 8, 9 and 10 each shipped zero new packages —
that is the bar.
-->

## Hardware / permissions

- [ ] Not applicable
- [ ] Applicable — the tool declares `requires="<capability>"` and the capability is registered

## Screenshots

<!-- Required for UI changes. -->
