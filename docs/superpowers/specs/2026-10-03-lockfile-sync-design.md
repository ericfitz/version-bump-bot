# Lockfile sync: design

Amends `2026-10-03-version-bump-bot-design.md`. Ships as version-bump-bot 1.1.0.

## Problem

Some lockfiles record the project's own version, next to its dependencies. `uv.lock` is one: it has a `[[package]]` entry for the project itself. A bump rewrites `pyproject.toml` but not that entry. The next `uv run` or `uv lock` on any machine then rewrites the lockfile, which leaves a dirty working tree that nobody asked for. Committing that change triggers yet another bump. Adopters can avoid this today only by knowing to add the lockfile as a regex target, which is a footgun.

## Human-made decisions (Eric Fitzgerald, 2026-10-03)

14. **Lockfiles are synced automatically, with no adopter config.** Using the bot in a repo with a lockfile must not require knowing about the lockfile.
15. **Scope:** `uv.lock`, `package-lock.json` / `npm-shrinkwrap.json`, and `Cargo.lock`. Yarn Berry is deferred.
16. **If a lockfile is found but the project's own entry is not, the bot skips that lockfile with a warning.** The bump goes ahead. A lockfile the bot does not understand must never block a release.

## Approach

The bot treats each lockfile it discovers as an extra target that it adds itself. A considered alternative was running each package manager's own lock command after the bump. It was rejected for three reasons:

- it needs the toolchains and network access in the bump job;
- it can pull unrelated dependency changes into the bot's commit;
- the guard can't check the result cheaply.

Detect-and-advise alone (a `doctor` hint) leaves the footgun in place.

## Detection

Detection runs wherever the config's streams are resolved for `plan`, `apply`, `guard` and `doctor`. It reads files at the ref being examined: the working tree for `plan` and `apply`, and the base and head commits for `guard`.

1. **Recognised manifests.** A stream file, whether source or target, is a manifest when its basename and spec match one of these rows:

   | Basename | Format and path | Lockfile kinds |
   |---|---|---|
   | `pyproject.toml` | `toml-path`, `project.version` | `uv.lock` |
   | `package.json` | `json-path`, `version` | `npm-shrinkwrap.json`, then `package-lock.json` |
   | `Cargo.toml` | `toml-path`, `package.version` | `Cargo.lock` |

   Other specs are never manifests: regex targets, `workspace.package.version`, and dynamic versions.

2. **Lockfile lookup.** Start in the manifest's directory and walk up to the repo root. The first directory that holds a lockfile of the manifest's kind wins. Only that lockfile is used. This covers workspaces, where uv, Cargo and npm keep one lockfile at the root.

3. **Package name.** The name comes from the manifest:
   - `pyproject.toml`: `project.name`;
   - `package.json`: `name`;
   - `Cargo.toml`: `package.name`.

   If there is no name, the lockfile is skipped with a warning.

4. **Deduplication.** If two streams resolve to the same lockfile entry, the first stream in config order owns it and the bot warns about the second. Different entries in one lockfile, such as two workspace members, are independent.

## Lockfile entries

| Kind | The entry | What is rewritten |
|---|---|---|
| `uv.lock` | the `[[package]]` table whose `name` equals the manifest name, compared after PEP 503 normalization, and whose `source` is `editable` or `virtual` | that table's `version = "X.Y.Z"` line |
| `Cargo.lock` | the `[[package]]` table whose `name` equals the manifest name and that has no `source` key (workspace members have none) | that table's `version = "X.Y.Z"` line |
| `package-lock.json`, `npm-shrinkwrap.json` (lockfileVersion 2 or 3) | `packages["<manifest dir relative to the lockfile dir>"]`, where `""` means the lockfile's own directory | that object's `version`; also the top-level `version` when the manifest sits next to the lockfile |

- **Edits.** Edits preserve every other byte, like the existing `toml-path` and `json-path` writers. Only the version string changes.
- **Ambiguity is a skip, not a guess.** If no entry matches, more than one matches, or the lockfile can't be parsed, the bot treats it as "entry not found": it warns (decision 16) and skips that lockfile.
- **Unsupported npm formats.** `lockfileVersion` 1 has no `packages` map, so it is skipped with a warning.

## Behaviour

- **`plan`** adds each discovered lockfile to the stream's `files`, so it is pre-checked, written and committed like any target. Skipped lockfiles are reported in a new `warnings` list in the plan JSON.
- **`apply`** writes each lockfile entry after the stream's targets.
- **`apply` repairs drift in other streams.** It also rewrites drifted entries in streams this plan does not bump, setting them to their stream's current version. Without that, the re-plan check below would fail the whole release over a stale entry in an unrelated stream (decision 16). *(Agent ruling, 2026-10-03, after the final review.)*
- **Only committed lockfiles.** `apply` and the re-plan check consider only lockfiles that are tracked at HEAD, because the bump commits with `git add -u`.
- **Re-plan check.** The empty re-plan after `apply` must also find every lockfile entry in agreement.
- **Warnings.** The bump workflow prints each warning as `::warning::`.
- **`guard`.** A lockfile entry fails the guard only if the PR **changed** it **and** the new value differs from the manifest's version at head. As a result:
  - hand edits that drift are caught;
  - a PR that repairs existing drift passes;
  - drift that a PR leaves untouched produces only a warning, which the next bump fixes.

  Skipped lockfiles are reported, never failed.
- **`doctor`** lists each discovered lockfile and its entry, or the reason it was skipped.
- **No opt-out in 1.1.** If one is ever needed, `[lockfiles] ignore = ["glob", ...]` can be added later.

## Rollout in this repo

- `version.yml` runs the bot from the merged commit itself, so the 1.1.0 PR is checked by the new guard.
- That PR also fixes `uv.lock`'s stale `0.1.0` to `1.0.0`. This is a repair, which the guard allows.
- The PR title is `feat: sync lockfiles that record the project's own version`, which releases 1.1.0. The release bump then writes `1.1.0` to both `pyproject.toml` and `uv.lock`.
- Verify afterwards that `uv lock --check` passes on `main`.

## Testing

- **Format tests** for each kind, against fixtures shaped like real lockfiles:
  - a single package;
  - a workspace member in a subdirectory;
  - a name that differs only by PEP 503 normalization (uv);
  - a dependency that has the same name as the project but has a `source` (Cargo);
  - npm `lockfileVersion` 1, 2 and 3.
- **Discovery tests:**
  - walk-up to the root;
  - the nearest lockfile wins;
  - a missing name;
  - an unknown spec that is not treated as a manifest;
  - two streams sharing one entry.
- **Guard tests:**
  - a drifting edit fails;
  - a repairing edit passes;
  - untouched drift warns.
- **End-to-end** in a scratch repo with a real-shaped `uv.lock`: bump, then assert that the lockfile entry equals the new version and that a re-plan is empty.
- No test runs `uv`, `npm` or `cargo`.
