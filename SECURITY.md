# Security

## Report privately

If you find a security problem or a leaked key, report it **privately**.

- Use GitHub Security Advisories on this repository.
- Or contact the maintainer without posting the secret.

Do **not** open a public issue that contains a key, token, password, or `.env` file.

## Do not commit secrets

- Copy `.env.example` to `.env` and fill in your own keys.
- Never commit `.env` or any other `*.env` file (except `.env.example`).
- Never put a real key in source, docs, tests, or HTML.

Public Talk on berkkarabacak.com is already set up for visitors. Your local clone uses only the keys you put in `.env`.
