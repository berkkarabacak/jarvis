from dotenv import load_dotenv
import os
load_dotenv(".env", override=True)
os.environ.setdefault("JARVIS_ENABLED", "true")
os.environ.setdefault("JARVIS_REALTIME", "true")
os.environ.setdefault("HOST", "127.0.0.1")
os.environ.setdefault("PORT", "8787")
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port=8787)
