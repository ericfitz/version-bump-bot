# version-bump-bot v1: execution notes

These are the agent rulings and deferred review findings from the subagent-driven execution of `2026-10-03-version-bump-bot.md` (branch feat/v1-implementation, 2026-10-03). Rulings are agent decisions, not human decisions; Eric reviews them. Final whole-branch review verdict: with fixes. The 2 Important findings were fixed and re-reviewed.

## Rulings

- Ruling: Task 1 .gitignore is a full REPLACE of the 220-line template, and must also list .superpowers/ (SDD scratch) — plan omitted it; .local/ and HANDOFF.md already added to plan — cost if wrong: trivial.
- Ruling R1: App needs Workflows: read/write to push the self-adoption bump (bump.yml/guard.yml are regex targets; GitHub rejects App-token pushes touching .github/workflows/ without it). Implement as planned; ESCALATED to Eric (spec App-permission change = human decision; spec not edited yet) — cost if wrong: first release push fails until permission added, or T14 redesign.
- Ruling R2 (T8): rewrite test_only_ignored_json_path_change_does_not_trigger to assert `not is_triggered(...)` on that commit and `plan_of(...).base == sha` — code matches spec rule 1; test was wrong — cost: none.
- Ruling R3 (T13): bump.yml uses `git commit -F "$RUNNER_TEMP/message.txt"` (no -q) so the test substring matches — cost: noisier log.
- Ruling R4 (T13): no job-level env using runner.temp; use "$RUNNER_TEMP/plan.json" in run steps — actionlint rejects runner in jobs.<id>.env — cost: none.
- Ruling R5 (T13): delete guard.yml "Fetch the base branch" step; fetch-depth 0 already has origin/<base> — cost: none.
- Ruling R6 (T12): detect_repo_slug uses `git config --get remote.origin.url` (no `git remote`, per Global Constraints) — cost: none.
- Ruling R7 (T1): track uv.lock (add to T1 git add) — reproducible CI — cost: lock churn on dep bumps.
- Ruling R8 (T8): cli imports DEFAULT_CONFIG_PATH from config; drop cli.DEFAULT_CONFIG — cost: none.
- Ruling R9: File Structure comment drift (FileSpec in formats.py, render_tag in plan.py) is doc-only; no task change — cost: none.
- Ruling R10 (T9/T10): shared `run_commands(repo, cmds, *, stream, kind)` in new src/version_bump/shell.py used by apply hooks and guard verify; keep messages "after hook failed"/"verify command failed". conftest.run_git duplicating gitops is fine — cost: one extra module.
- Ruling R11 (T7/T6): drop gitops.head_tree_clean and its test (no consumer, YAGNI); ignore T6's stray LEVELS consume — cost: none.
- Ruling R12 (T9): apply pre-checks all plan.streams[].files exist before writing anything (no partial write) — cost: 4 lines.
- Ruling R13 (T9/T14): rename tests to test_apply_rewrites_corrupted_target_from_source and test_worktree_replan_fails_when_target_disagrees_after_partial_apply — cost: none.
- Ruling (T1): ruff.toml extend-exclude ["docs", ".superpowers"] accepted — ruff 0.16 formats Markdown code blocks and the plan's code is intentionally unformatted; docs are not shipped code — cost if wrong: docs code samples unlinted.
- Ruling (T5): fix all three despite plan text — spec mandates byte preservation ("writers change only the version value"), prerelease untouched, and ConfigError for config problems; plan code contradicts spec — cost if wrong: none (stricter behavior).
- Ruling (T5): Minor #5 ([[array-of-tables]] TOML headers unrecognised) upgraded to Important and included in fix round — realistic pyproject.toml layouts would edit the wrong key — cost if wrong: small extra code.
- Ruling (T6): fix despite plan text — plan Review Focus #2 + spec require one-line ConfigError, no traceback — cost if wrong: none.
- Ruling (T7): GIT_CONFIG_GLOBAL=/dev/null applies to the test fixture only (Global Constraint 'Fixture hygiene'), not gitops runtime — runtime must honor global config (e.g. safe.directory on CI runners) — cost if wrong: a dev's global git config could affect local CLI runs.
- Ruling (T7): fix both Important (byte-preservation constraint; DRY) and remove GIT_CONFIG_NOSYSTEM from runtime env (keep in fixture), docstring updated — extends prior GIT_CONFIG_GLOBAL ruling — cost if wrong: system git config could affect runs.
- Ruling (T8): accept both deviations — test regex matches the brief/spec message; byte-decoding matches T7 CRLF ruling — cost if wrong: none.
- Ruling (T8): route confirmed ⚠️ gaps + minor #3 into fix round 1 — Review Focus #2 is binding — cost if wrong: extra tests only.
- Ruling (T11): extract cli._repo_and_config(args) -> (Path, Config) now and use it in plan/apply/guard/tag (and doctor in T12) — the brief assumed it existed; prevents 5x duplication — cost if wrong: trivial.
- Ruling (T12): cmd_doctor resolves repo without _repo_and_config — doctor must report an invalid config as a finding, not abort; refines T11 helper ruling — cost if wrong: none.
- Ruling (T12): fix both + add cmd_doctor e2e test + non-numeric app id → one-line error (minor #3 folded in) — spec: doctor prints exact, safe fix commands — cost if wrong: none.
- Ruling (T13): SHA-pin all actions in bump/guard/release-alias with # vX.Y.Z comments + test; NO dependabot config (deps-bump-bot's domain) — supply-chain hardening, no architecture change — cost if wrong: manual action updates until deps-bump-bot adopts.
- Ruling (T13 ⚠️ v0 alias): not an issue — first self-adoption merge is the fold base (no tag), first real release is feat! → 1.0.0 → v1.0.0 → alias v1; v0 never created — cost if wrong: a stray v0 alias tag.
- Ruling (final): fix Important 1 by tagging locally after commit and pushing branch + tags in ONE `git push --atomic` (deviates from spec step order 7→8; strictly safer: tag conflicts fail before anything is pushed, no half-done state) — cost if wrong: an adopter tag ruleset could now block the branch push too (fails loudly, nothing partial).
- Ruling (final): fix Important 2 (README adoption/release ordering, pre-existing-source warning, Workflows permission stated as required for self-adoption release, pending Eric).
- Ruling (final): also fold in recommended can-waits BREAKING_RE/FEAT_RE greedy scope (`\([^)]*\)`) and `::stop-commands::` around plan/log stdout — cheap, adopter-visible correctness/safety — cost if wrong: none. Other ledger minors: can-wait (triaged in final-review.md).

## Deferred minor findings (can wait, triaged in the final review)

- Task 1: minor (deferred): ci.yml uses `uv run` without --locked (lock drift silently rewritten)
- Task 1: minor (deferred): ci.yml actionlint install curl|bash unpinned from main; uses ${{ runner.temp }} in shell (plan-mandated)
- Task 1: minor (deferred): ci.yml pytest step name references actionlint/release-tag tests that arrive in T13/T14 — verify they exist at final review
- Task 1: minor (deferred): .gitignore dropped .env/.envrc from template — consider adding back
- Task 2: minor (deferred): semver SEMVER_RE `$` accepts trailing newline (use \Z) (plan-mandated)
- Task 2: minor (deferred): BREAKING/FEAT regex scope `\(.+\)` greedy — "fix(a): revert (b)!: c" reads as breaking; use `\([^)]*\)` (plan-mandated) — final review should weigh fixing
- Task 2: minor (deferred): Version.bump treats unknown level as patch; bump_level returns breaking unvalidated (config validates?)
- Task 2: minor (deferred): `(0|[1-9]\d*)` duplicated 6x across two regexes
- Task 2: minor (deferred): VERSION_PREFIX_RE has no direct test (exercised in T5?)
- Task 3: minor (deferred): pathglob `$` matches before trailing \n (plan-mandated; no caller produces such paths)
- Task 3: minor (deferred): stray `**` not adjacent to `/` compiles to `.*` crossing `/` (gitignore treats as `*`)
- Task 3: minor (deferred): no tests for bare `**`, empty pattern, regex-special escaping beyond `.`
- Task 4: minor (deferred): jsonpos returns first duplicate key's span while json.loads uses the last (plan-mandated; read/write could disagree on duplicate-key JSON)
- Task 4: minor (deferred): jsonpos docstring says "byte span" but returns str indices — T5 must slice the decoded str (carried to T5 dispatch)
- Task 4: minor (deferred): no direct tests for split_path invalid input / array sibling skipping
- Task 5: minor (deferred): regex component group int(g) raises bare ValueError on permissive user regex (e.g. \d*) — should be FormatError
- Task 5: minor (deferred): no test for json-semver nested path
- Task 5: minor (deferred): read/write dispatch is two parallel if-chains over FORMATS (dict would be cleaner)
- Task 6: minor (deferred): config.py compile_glob validation loops validate nothing (pathglob never raises) — dead code
- Task 6: minor (deferred): inconsistent locator style in config error messages
- Task 6: minor (deferred): `[stream]` single table gives "at least one [[stream]] is required" (misleading)
- Task 6: minor (deferred): load_config: directory path → "not found"; PermissionError/UnicodeDecodeError propagate raw
- Task 6: minor (deferred): test gaps (source missing, targets not list, trigger not table, tag non-string, merge not table)
- Task 7: minor (deferred): show_file on a directory path returns tree listing, not None
- Task 7: minor (deferred): pathspec magic live in gitops path args (paths with * ? [ or leading :) — consider --literal-pathspecs
- Task 7: minor (deferred): `git log -1 --format=%s <sha>` lacks trailing `--` (ambiguous if a path matches)
- Task 7: minor (deferred): check=False maps all git failures to None (conflates "absent" with "broken")
- Task 7: minor (deferred): conftest run_git lacks encoding/errors args
- Task 7: minor (deferred): test gaps (rev_parse success, directory path, create_tag cases)
- Task 8: minor (deferred): to_json ensure_ascii=False + surrogateescape subjects → writing plan JSON could raise UnicodeEncodeError on invalid-UTF-8 commit subject (Review Focus #1 "never crash") — final review should weigh
- Task 8: minor (deferred): _worktree_value called twice per stream
- Task 8: minor (deferred): "no commit on <ref>" message shows resolved 40-char sha instead of ref name
- Task 8: minor (deferred): ref value read before worktree self-consistency check (error precedence differs from brief)
- Task 9: minor (deferred): apply pre-check iterates plan.files but writes iterate config files — a plan/config mismatch could still partial-write
- Task 9: minor (deferred): cli repo/config resolution duplicated across cmd_plan/cmd_apply — extract helper
- Task 9: minor (deferred): apply._read is_file check unreachable after pre-check, different message
- Task 9: minor (deferred): test_shell `cat` DEVNULL test only discriminates on interactive fd 0
- Task 9: minor (deferred): `apply --plan -` stdin branch untested
- Task 9: minor (deferred): apply._read_text duplicates plan._read_text
- Task 10: minor (deferred): cli guard `checked` count is substring-based, untested with skipped stream (plan-mandated)
- Task 10: minor (deferred): no tests for target-absent-at-base skip and `<absent>` deleted-at-head path
- Task 10: minor (deferred): `--head` lacks help; verify runs in working tree, not at --head ref
- Task 10: minor (deferred): repo/config resolution duplicated 3x in cli.py (helper never existed)
- Task 10: minor (deferred): errors.py docstring says "one line" but GuardError is multi-line
- Task 11: minor (deferred): tags dedupe untested; CLI tag conflict path (exit 1, stderr) untested; non-default --commit untested; lib/ tag target not asserted
- Task 11: minor (deferred): cmd_tag loads and discards Config (fails on bad config though it only needs the plan) — consequence of T11 helper ruling
- Task 12: minor (deferred): actors/contexts aggregated across all rulesets but fix PUTs only rulesets[0]
- Task 12: minor (deferred): config finding prints the same error twice (FAIL + fix)
- Task 12: minor (deferred): rule["parameters"]/c["context"] direct indexing — KeyError on unusual ruleset JSON
- Task 12: minor (deferred): test_multiple_rulesets_and_custom_check_name uses single-ruleset fixture (misnamed)
- Task 13: minor (deferred): skip guard uses inputs.app_slug while commit identity uses minted app-slug — mismatch fails open (fold-base guard still prevents cascade)
- Task 13: minor (deferred, WEIGH AT FINAL): tag push failure after commit push leaves tags never created (rerun plan empty, no recovery)
- Task 13: minor (deferred): non-ruleset push failures reported as "must be bypass actor"
- Task 13: minor (deferred): cat plan.json / git log print commit subjects to stdout — workflow-command (::) injection surface; consider ::stop-commands::
- Task 13: minor (deferred): guard.yml on non-PR event: opaque merge-base error, add explicit BASE check
- Task 13: minor (deferred): interpolation test is a narrow substring check (plan-mandated)
- Task 13: minor (deferred): test_release_tag re-reads pyproject per iteration
- Task 14: minor (deferred): self-adoption test checks config shape, not that regex targets resolve
- Task 14: minor (deferred, WEIGH AT FINAL): README Releasing omits that App+secrets must exist BEFORE first merge to main
- Task 14: minor (deferred): README plan JSON key list omits `ref`
- Task 14: minor (deferred): README omits bump.yml `app_slug` and both workflows' `config` inputs
- Task 14: minor (deferred): e2e doesn't assert verify command ran

## Runtime-only checks for the first self-adoption run

- Task 13: ⚠️ runtime-only (verify on first self-adoption run): github.actor == <slug>[bot] for App pushes; App-token push triggers caller workflow + tag → release-alias; token mint; push-rejection branch; gh api users/<slug>[bot] with installation token; fork-PR head fetch in guard.

## Final-review triage of deferred findings


Task 1
- ci.yml `uv run` without `--locked` — can-wait (recommend `--locked`; lock is tracked per R7).
- actionlint installer curl|bash from `main`, `${{ runner.temp }}` in shell — can-wait (CI-only, not the reusable path).
- pytest step name references actionlint/release-tag tests — resolved: both tests exist (test_workflows.py, test_release_tag.py).
- .gitignore dropped .env/.envrc — can-wait.
Task 2
- SEMVER_RE `$` accepts trailing newline — can-wait (values are stripped or regex-captured upstream).
- BREAKING/FEAT scope `\(.+\)` greedy — can-wait, but recommend fixing now (Minor 1; cheap, protects against a wrong major).
- Version.bump unknown level -> patch; bump_level returns `breaking` unvalidated — can-wait (config validates `breaking`).
- `(0|[1-9]\d*)` duplicated — can-wait.
- VERSION_PREFIX_RE untested directly — can-wait (exercised via formats tests).
Task 3
- pathglob `$` before trailing `\n` — can-wait (git never yields such paths).
- stray `**` not adjacent to `/` crosses `/` — can-wait; document.
- missing tests for bare `**`, empty pattern, escaping — can-wait.
Task 4
- jsonpos first-duplicate-key vs json.loads last — can-wait (duplicate-key JSON is malformed in practice).
- "byte span" docstring vs str indices — can-wait (T5 slices the str consistently).
- split_path / array sibling tests — can-wait.
Task 5
- `int(g)` bare ValueError on permissive regex (`\d*`) — can-wait (fold into Minor 3's error-wrapping).
- no json-semver nested-path test — can-wait.
- parallel if-chains over FORMATS — can-wait.
Task 6
- compile_glob validation loops are dead code — can-wait.
- inconsistent locator style in messages — can-wait.
- `[stream]` single table message — can-wait.
- directory path -> "not found"; PermissionError/UnicodeDecodeError propagate — can-wait (Minor 3).
- config test gaps — can-wait.
Task 7
- show_file on a directory returns tree listing — can-wait.
- pathspec magic in gitops path args — can-wait (Minor 8).
- `git log -1 --format=%s` lacks `--` — can-wait (Minor 8).
- check=False conflates absent/broken — can-wait.
- conftest run_git lacks encoding args — can-wait.
- gitops test gaps — can-wait.
Task 8
- to_json ensure_ascii=False + surrogateescape crash — can-wait: did not reproduce (invalid-UTF-8 subject, `LC_ALL=en_US.UTF-8`, stdout to a file: exit 0); GitHub also guarantees valid UTF-8 PR titles. Still worth `errors="surrogateescape"` on the write for belt-and-braces.
- `_worktree_value` called twice per stream — can-wait.
- "no commit on <ref>" shows the sha — can-wait.
- ref value read before worktree check (error precedence) — can-wait.
- `_json_differs_ignoring` parse-failure path untested — can-wait.
Task 9
- apply pre-check iterates plan.files but writes config files — can-wait (same run, same config).
- cli repo/config duplication — resolved by T11 ruling (`_repo_and_config`).
- `apply._read` is_file check unreachable — can-wait.
- test_shell `cat` DEVNULL discrimination — can-wait.
- `apply --plan -` untested — can-wait.
- `_read_text` duplicated — can-wait.
Task 10
- guard `checked` count substring-based — can-wait.
- target-absent-at-base / `<absent>` tests — can-wait.
- `--head` help; verify runs in working tree — can-wait (guard.yml checks out head, so tree == head).
- repo/config duplication — resolved (T11).
- errors.py "one line" vs multi-line GuardError — can-wait (intended; adjust docstring).
- note: spec rule 5 satisfied only via base-vs-head comparison — can-wait: the bump's worktree check and `apply` rewriting targets make drift self-healing; add a README sentence that guard compares base-to-head values and does not independently assert target==source at head.
Task 11
- tags dedupe/conflict/non-default --commit untested — can-wait.
- cmd_tag loads and discards Config — can-wait.
Task 12
- actors/contexts aggregated across rulesets, fix PUTs rulesets[0] — can-wait (document in the finding text).
- config finding prints the error twice — can-wait.
- `rule["parameters"]`/`c["context"]` direct indexing — can-wait.
- misnamed multi-ruleset test — can-wait.
Task 13
- skip guard uses inputs.app_slug vs minted slug — can-wait (Minor 9).
- WEIGH AT FINAL: tag push failure after commit push unrecoverable — fix-before-merge (Important 1).
- non-ruleset push failures reported as bypass actor — can-wait (Minor 5; git's stderr is in the log above).
- `::` workflow-command surface from `cat plan.json`/`git log` — can-wait (Minor 4).
- guard.yml on non-PR event: opaque merge-base error — can-wait (never called on non-PR by the documented caller).
- interpolation test is a narrow substring check — can-wait.
- test_release_tag re-reads pyproject — can-wait.
Task 14
- self-adoption test checks shape, not that regex targets resolve — can-wait (the simulation above resolved both targets; `test_embedded_release_tag_matches_pyproject_in_every_reusable_workflow` covers the constant).
- WEIGH AT FINAL: README Releasing omits App+secrets before first merge — fix-before-merge (Important 2).
- README plan JSON omits `ref` — can-wait (Minor 10).
- README omits `app_slug`/`config` inputs — can-wait (Minor 10).
- e2e does not assert verify ran — can-wait.

