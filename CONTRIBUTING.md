# Contributing to Accentor

Thank you for your interest in Accentor. Whether you are fixing a typo, adding a
provider adapter, writing a new focused example, or improving documentation, your
contribution matters and we are glad you are here.

Accentor is in **alpha**. The surface area is still settling, which means there
is a lot of room to shape the project — and also means things may shift under
you. When in doubt, open an issue or start a discussion before investing
significant effort in a large change.

## Ways to Contribute

Code is one way to help, but not the only one:

- **Report bugs** — file a [bug report](.github/ISSUE_TEMPLATE/bug_report.md)
  with steps to reproduce.
- **Request features** — open a
  [feature request](.github/ISSUE_TEMPLATE/feature_request.md) describing the
  problem you want solved.
- **Improve documentation** — clarify a confusing section, fix a broken link,
  or add a missing example.
- **Write a focused example** — show how Accentor applies to a domain you know.
  See `examples/focused_examples/` for the current set.
- **Add a provider adapter** — bring a new LLM provider into
  `accentor.dispatch.agents.providers`.
- **Review pull requests** — a second set of eyes catches things automated
  checks cannot.
- **Try the library and share what you learn** — blog posts, talks, and
  conversations help the project grow.

## Getting Started

### Prerequisites

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip

### Clone and Install

```bash
git clone https://github.com/accentor-ai/py-accentor.git
cd py-accentor
uv venv && source .venv/bin/activate
uv pip install -e ".[dev,docs]"
```

### Verify Your Setup

```bash
pytest
```

All tests should pass. The default test suite is deterministic and fully offline
— no API keys or network access required.

## Branching and Releases

Accentor uses two long-lived branches:

- **`dev`** — the integration branch where all contributor work lands.
- **`main`** — the stable branch. Merges from `dev` to `main` happen less
  frequently and correspond to version releases published to PyPI. Each release
  typically bundles multiple changes from across the repo.

**All pull requests should target `dev`**, not `main`.

## Development Workflow

1. **Create a feature branch** from `dev`:
   ```bash
   git checkout dev && git pull
   git checkout -b your-branch-name
   ```
2. **Make your changes.** Keep each pull request focused on a single logical
   change.
3. **Write or update tests** for any new or modified behavior.
4. **Run the test suite** before opening a PR:
   ```bash
   pytest
   ```
5. **Push your branch** and open a pull request against `dev`.

### Discuss Before Building

For anything beyond a small fix, **open an issue first** to describe what you
want to change and why. This saves everyone time — we can align on approach
before you write the code.

## Testing

The test suite lives in `tests/` and uses **pytest**.

- Tests must be **deterministic and offline**. When running `pytest tests/`,
  no test may call a real LLM provider, installed agent CLI, hosted model, or
  live network-backed adapter.
- Use `MockAgent` for all test paths that involve an agent. Tests for live
  adapter code, such as `CodexCli`, must mock subprocess/provider boundaries
  rather than invoking the installed CLI.
- Do not add live-provider calls to unit, contract, scenario, policy, golden, or
  smoke test lanes.
- Live provider integration testing uses separate tooling and is not required
  for CI or release gating.

## Code Style

- Write clear, readable Python. Favor explicit code over clever shortcuts.
- Keep docstrings concise — one line when possible.
- We may introduce a formatter and linter (likely Ruff) as the project matures.
  For now, match the style of the surrounding code.

## Documentation

Docs are built with Sphinx and live in `docs/`.

```bash
uv pip install -e ".[docs]"
sphinx-build -b html docs docs/_build/html
open docs/_build/html/index.html
```

If your change affects behavior, update the relevant documentation in the same
PR.

## Security

If you discover a security vulnerability, **do not open a public issue**. Email
the maintainers directly so the issue can be addressed before disclosure.

Contributions touching validation or workspace policy must ensure that secrets
never leak into prompts, staged workspaces, public artifacts, or logs.

## Pull Request Guidelines

- **One logical change per PR.** Smaller PRs are easier to review and merge.
- **Describe the problem and your solution** in the PR description. Link to any
  related issue.
- **Include tests.** If a PR changes behavior, it should include a test that
  would have failed before the change.
- **Keep the diff minimal.** Avoid unrelated formatting changes, refactors, or
  dependency bumps in the same PR.

## What Not to Commit

The `.gitignore` covers most of this, but as a reminder — do not commit:

- `docs/_build/`, `.venv/`, `dist/`
- Coverage output, caches, or local artifacts
- Private working notes or credentials

## Community

- Be respectful. Treat every contributor — regardless of experience level — as a
  peer.
- Assume good intent. If something seems off, ask before assuming.
- We are building this together. Your perspective makes the project better.

## License

By contributing to Accentor, you agree that your contributions will be licensed
under the [MIT License](LICENSE).
