# Releasing

This project is ready to build as a normal Python package.

## Build locally

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

## Publish to PyPI

If you have a PyPI API token available in your shell:

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-...
python -m twine upload dist/*
```

## Notes

- The package name checked for the first release is `conjira-cli`.
- `conjira-setup-macos` is included as a console script entrypoint.
- macOS setup remains optional. Windows and Linux users can still use env vars or token files.
