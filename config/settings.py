import os
from dotenv import load_dotenv

load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Default is True to prevent accidental real money usage unless specified
IS_TESTNET = os.getenv("IS_TESTNET", "True").lower() in ("true", "1", "t")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
