# Releasing

This project can be released either with a one-off local Twine upload or, preferably, with PyPI Trusted Publishing from GitHub Actions.

## Preferred path: GitHub Actions Trusted Publishing

### 1. Configure PyPI once

In the PyPI project settings for `conjira-cli`, add a Trusted Publisher that matches this repository:

- Owner: `quanttraderkim`
- Repository: `conjira-cli`
- Workflow file: `.github/workflows/publish.yml`
- Environment name: `pypi`

After that one-time setup, PyPI no longer needs an API token for normal releases from GitHub Actions.

### 2. Bump the version and merge it to `main`

Update both of these files:

- `pyproject.toml`
- `src/conjira_cli/__init__.py`

### 3. Run the publish workflow

Open the GitHub Actions tab and run `Publish to PyPI` manually. The workflow builds the package, runs `twine check`, and publishes with OIDC Trusted Publishing.

## Local fallback: Twine upload

If Trusted Publishing is not ready yet, you can still publish from a local shell with a PyPI API token:

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-...
python3 -m pip install --user --upgrade build twine
python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*
```

## Notes

- The package name is `conjira-cli`.
- `conjira-setup-macos` is included as a console script entrypoint.
- macOS setup remains optional. Windows and Linux users can still use env vars or token files.
