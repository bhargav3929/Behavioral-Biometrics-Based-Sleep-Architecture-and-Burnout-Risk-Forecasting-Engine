"""All settings, read once from the environment (.env is loaded first)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)

VERSION = "1.0.0"
PLACEHOLDER_KEY = "your_groq_key_here"


def _s(name: str, default: str) -> str:
    v = os.environ.get(name)
    return default if v is None or v.strip() == "" else v.strip()


def _b(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("true", "1", "yes", "y", "on")


def _i(name: str, default: int) -> int:
    try:
        return int(float(_s(name, str(default))))
    except ValueError:
        return default


def _f(name: str, default: float) -> float:
    try:
        return float(_s(name, str(default)))
    except ValueError:
        return default


PROJECT_NAME = _s("PROJECT_NAME", "Behavioral Biometrics Based Sleep Architecture and Burnout Risk Forecasting Engine")
PROJECT_SLUG = _s("PROJECT_SLUG", "sleep-burnout-forecasting")
PROJECT_NUMBER = _i("PROJECT_NUMBER", 10)
HOST = _s("HOST", "127.0.0.1")
PORT = _i("PORT", 8010)
MAX_UPLOAD_MB = _i("MAX_UPLOAD_MB", 2)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = _s("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = _s("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")

DEMO_MODE = _b("DEMO_MODE", False)
DEMO_TICKET_SECRET = os.environ.get("DEMO_TICKET_SECRET", "").strip()
DEMO_DAILY_CAP = _i("DEMO_DAILY_CAP", 200)
DEMO_MAX_UPLOAD_MB = _i("DEMO_MAX_UPLOAD_MB", 1)
TRUST_PROXY = _b("TRUST_PROXY", False)

TARGET_SLEEP_HOURS = _f("TARGET_SLEEP_HOURS", 8.0)
SAFE_CAFFEINE_MG = _f("SAFE_CAFFEINE_MG", 400.0)

HOURLY_RUNS = 15
HOURLY_WINDOW_SECONDS = 3600

DATA_DIR = Path(os.environ.get("SLEEP_DATA_DIR") or (ROOT / "data"))
DB_PATH = DATA_DIR / "sleep_burnout.db"
SAMPLES_DIR = ROOT / "samples"
RESULTS_DIR = SAMPLES_DIR / "results"
STATIC_DIR = ROOT / "static"

DISCLAIMER = (
    "Wellness & Educational Forecasting Only — Not Medical Advice: This tool estimates behavioral "
    "fatigue patterns from self-logged habits and does not diagnose sleep disorders or medical conditions. "
    "Consult a qualified healthcare professional for persistent insomnia or exhaustion."
)
