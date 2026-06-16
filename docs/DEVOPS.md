# DevOps guide

How `suu` is built, tested, and released. Audience: maintainers.

- **Package name (PyPI):** `suu`
- **Import package:** `suu` (src layout under `src/suu/`)
- **Repo:** https://github.com/MaybeItsAdam/suu
- **CI/CD:** GitHub Actions — [`.github/workflows/release.yml`](../.github/workflows/release.yml)
- **Publishing:** PyPI Trusted Publishing (OIDC) — **no API tokens stored in GitHub**

---

## TL;DR — how to ship a release

```bash
# 1. make your changes, then bump the version
#    edit pyproject.toml:  version = "0.1.2"
git commit -am "your change + bump to 0.1.2"

# 2. push to main  → CI builds, tests, and publishes to TestPyPI (staging)
git push origin main
#    check it looks right: https://test.pypi.org/project/suu/

# 3. tag the release  → CI builds, tests, then waits for your approval, then PyPI
git tag v0.1.2
git push origin v0.1.2
#    approve the deployment (see "Approving a release" below) → live on PyPI
```

Rule of thumb: **the git tag must equal the `pyproject.toml` version** (`v0.1.2` ⇄ `0.1.2`). CI fails the release if they differ.

---

## The pipeline

One workflow, `Build & Publish`, triggered by:

| Trigger | What runs | Publishes to |
| :--- | :--- | :--- |
| Push to `main` | build → test → publish | **TestPyPI** (`skip-existing: true`) |
| Push tag `v*` | build → test → version-guard → **approval** → publish | **PyPI** |

Jobs:

1. **build** — `python -m build` (sdist + wheel), `twine check`, uploads `dist/` as an artifact.
2. **test** — `pip install -e ".[dev,forms]"` then `pytest`, on Python **3.10** and **3.12**.
3. **publish-testpypi** — runs only on `main`. Downloads the built artifact and publishes to TestPyPI. `skip-existing` means re-pushing the same version to `main` won't fail.
4. **publish-pypi** — runs only on `v*` tags. Re-checks the tag matches the version, then publishes to PyPI. Gated by the `pypi` GitHub Environment (manual approval).

Build happens once; both publish jobs consume the same artifact, so what's tested is exactly what's shipped.

### Why TestPyPI first
`main` is the staging lane. Every merge lands on TestPyPI so you can eyeball the rendered project page (README, logo, metadata) and do a trial install before cutting a real tag. Real PyPI versions are **immutable** — you can never re-upload `0.1.2` once it exists, so catching mistakes on TestPyPI matters.

---

## Approving a release

Tag pushes pause at the `pypi` environment's required-reviewer gate. Approve via either:

**GitHub UI:** open the run from the [Actions tab](https://github.com/MaybeItsAdam/suu/actions) → **Review deployments** → check `pypi` → **Approve and deploy**.

**CLI:**
```bash
RID=$(gh run list --limit 1 --json databaseId -q '.[0].databaseId')
# find the pending environment id:
gh api repos/MaybeItsAdam/suu/actions/runs/$RID/pending_deployments \
  -q '.[].environment | {name, id}'
# approve (environment_ids must be a JSON array):
echo '{"environment_ids":[<ENV_ID>],"state":"approved","comment":"release"}' \
  | gh api -X POST repos/MaybeItsAdam/suu/actions/runs/$RID/pending_deployments --input -
```

---

## One-time infrastructure setup

Already configured for this repo — documented here for disaster recovery or forks.

### Trusted publishing (OIDC)
No tokens. Each index is told to trust this repo + workflow + environment.

- **PyPI:** https://pypi.org/manage/project/suu/settings/publishing/ → add publisher:
  Owner `MaybeItsAdam`, Repo `suu`, Workflow `release.yml`, Environment `pypi`.
- **TestPyPI:** https://test.pypi.org/manage/project/suu/settings/publishing/ → same, Environment `testpypi`.

### GitHub Environments
Repo **Settings → Environments**:
- `testpypi` — no protection needed.
- `pypi` — add **Required reviewers** (yourself) so production releases need a click.

If OIDC ever fails with a permissions error, confirm the publish job has `permissions: id-token: write` (it does) and that the publisher config above matches exactly.

---

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all,dev]"      # everything + test tools
playwright install chromium      # needed for forms/mcp/poll at runtime

pytest                           # run the test suite
suu --help                       # smoke-test the CLI
```

Extras (install only what you need):

| Extra | Pulls in | For |
| :--- | :--- | :--- |
| `scrape` | selenium, bs4, openpyxl, supabase, … | `suu scrape`, `suu whatson` |
| `forms` | playwright, httpx | `suu forms`, and the `suu poll` worker |
| `mcp` | fastmcp, playwright, httpx | `suu mcp` |
| `all` | scrape + forms + mcp | everything |
| `dev` | pytest, pytest-asyncio, pytest-playwright | running tests |

### Building locally (to inspect a wheel before pushing)
```bash
rm -rf dist build src/*.egg-info
python -m build
twine check dist/*
unzip -l dist/*.whl | grep -E "definitions|logo.png"   # confirm data files ship
```

### Bundled data files
Non-`.py` files only ship if listed in `[tool.setuptools.package-data]`:
- `suu.forms` → `definitions/*.json` (the form definitions)
- `suu.mcp` → `logo.png` (served by the MCP server at `logo://png`)

If you add a new data file (image, JSON, template), **add it there** or it won't be in the wheel — and the bug won't show until someone `pip install`s the published package.

---

## Manual publish (fallback only)

If Actions is down and you must publish by hand. Tokens live in a git-ignored `.env`
(`PYPI=` and `TESTPYPI=`, both `pypi-…` API tokens):

```bash
python -m build
export TWINE_USERNAME=__token__
# TestPyPI:
export TWINE_PASSWORD=$(grep '^TESTPYPI=' .env | cut -d= -f2-)
twine upload --repository testpypi dist/*
# real PyPI:
export TWINE_PASSWORD=$(grep '^PYPI=' .env | cut -d= -f2-)
twine upload dist/*
```

> Prefer the pipeline. Manual uploads skip the test gate and the approval step.
> **Never commit `.env`** — it's in `.gitignore`; keep it that way.

---

## Versioning

[SemVer](https://semver.org/): `MAJOR.MINOR.PATCH`.
- **PATCH** (`0.1.1`→`0.1.2`) — bug fixes, packaging fixes.
- **MINOR** (`0.1.x`→`0.2.0`) — new commands/features, backward-compatible.
- **MAJOR** (`0.x`→`1.0.0`) — breaking changes.

The version lives **only** in `pyproject.toml` (`[project] version`). Bump it, commit, then tag to match.

---

## Repo-specific gotchas

- **Git commit signing / USB key.** The maintainer's shell wraps `git` to GPG-sign
  commits, falling back to unsigned when the signing USB key is absent. That wrapper
  **breaks `git rebase --continue/--skip/--abort`** because it blindly appends
  `--no-gpg-sign` (which `rebase` subcommands reject). If a rebase errors with a
  `git rebase` usage message, bypass the wrapper and disable signing inline:
  ```bash
  command git -c commit.gpgsign=false rebase --continue
  ```
  If the rebase stored a forced-sign option, remove it first:
  `rm -f .git/rebase-merge/gpg_sign_opt`.

- **Node 24 / artifact actions.** `upload/download-artifact@v5` still bundle Node 20.
  The workflow sets `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"` to silence the
  deprecation warning; drop that env once those actions ship a Node 24 build.

- **TestPyPI duplicate versions.** TestPyPI also rejects re-uploading an existing
  version, but the `main` job uses `skip-existing: true` so repeated pushes on the
  same version are a no-op rather than a failure. Bump the version to actually publish
  something new there.

- **README images on PyPI.** PyPI doesn't render relative image paths, so the README
  logo uses a raw GitHub URL
  (`https://raw.githubusercontent.com/MaybeItsAdam/suu/main/assets/logo.png`).
  It only resolves once `assets/logo.png` is on `main`.
