"""Record model IDs visible to the controller's key on the official DeepSeek API."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
URL = "https://api.deepseek.com/models"


def main():
    key = (ROOT / "apikey.txt").read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError("Empty controller key")
    request = Request(URL, headers={"Authorization": "Bearer " + key})
    with urlopen(request, timeout=20) as response:
        ids = sorted(model["id"] for model in json.load(response)["data"])
        record = {"utc": datetime.now(timezone.utc).isoformat(), "method": "GET",
                  "url": URL, "http_status": response.status, "model_ids": ids}
    dest = ROOT / "reports/evidence/stage-01/models.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes((json.dumps(record, indent=2) + "\n").encode())
    print("HTTP", record["http_status"], ", ".join(ids))


if __name__ == "__main__":
    main()
