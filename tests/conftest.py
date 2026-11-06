import os
import sys
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="anikoto-test-")
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["CRAWL_ON_STARTUP"] = "false"
os.environ["ADMIN_TOKEN"] = "secret"
os.environ["RATE_LIMIT_REQUESTS"] = "1000"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
