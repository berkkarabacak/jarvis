# Jarvis

An open-source agent runtime you can talk to. It uses a real computer (Linux desktop, optional Android box).

**Live demo:** [https://aicontrolroom.nl/](https://aicontrolroom.nl/)

Alias: [https://berkkarabacak.com/jarvis/](https://berkkarabacak.com/jarvis/)

Talk in the browser, or download Windows from that page.

## Run it here

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8787
```

On Windows, activate with `.venv\Scripts\activate` instead of `source`.

Talk page: `http://127.0.0.1:8787/ceo`

Windows installer: `scripts\windows\build-installer.ps1`

## Keys

When you run Jarvis yourself, put your own keys in `.env` (copy from `.env.example`):

- `OPENAI_API_KEY=`
- `OPENROUTER_API_KEY=`

Never commit `.env` or any real key. Public Talk on [aicontrolroom.nl](https://aicontrolroom.nl/) is already free for visitors — you do not need a key there. [berkkarabacak.com/jarvis](https://berkkarabacak.com/jarvis/) is an alias.

## His computer

Jarvis has his own Linux desktop (`deploy/jarvis-computer`, ORCH-401).
Settings can switch that slot to Android (`deploy/jarvis-android`, ORCH-461).
Same Jarvis. Same memory. Different box. Default is Linux.
That Android box is not the phone app.

## Tests

```bash
pytest -q
```

## License

MIT. See [LICENSE](LICENSE). Pull requests welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
