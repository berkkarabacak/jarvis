# Contributing

Thanks for helping with Jarvis.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Put your own keys in `.env` if you need live Talk. Never commit that file.

## Tests

```bash
pytest -q
```

Install tools with `requirements-dev.txt` (pytest, ruff, mypy).

## Send a change

1. Branch from `main`.
2. Keep the change focused.
3. Run `pytest -q`.
4. Open a pull request against `main`.

Do not commit `.env`, keys, tokens, or passwords. If you find a leaked secret, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
