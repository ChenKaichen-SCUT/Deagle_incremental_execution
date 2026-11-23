"""Create the guide's empty directories and check key metadata without reading its contents."""

import json
import platform
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = (
    "configs", "third_party/deagle-baseline", "third_party/deagle-work",
    "third_party/damer-camc", "third_party/mini-swe-agent", "third_party/yogar-cbmc-inc",
    "incdeagle", "scripts", "schemas", "patches", "cases", "tests", "runs", "reports",
    "reports/evidence/stage-00",
)


def key_metadata(path):
    result = {"exists": path.exists(), "regular_file": path.is_file(),
              "nonempty": None, "readable": False}
    if result["regular_file"]:
        result["nonempty"] = path.stat().st_size > 0
        try:
            with path.open("rb"):
                result["readable"] = True
        except PermissionError:
            pass
    return result


def main():
    for directory in DIRECTORIES:
        (ROOT / directory).mkdir(parents=True, exist_ok=True)
    evidence = {
        "observed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": platform.system(),
        "project_root": str(ROOT),
        "directories_present": [d for d in DIRECTORIES if (ROOT / d).is_dir()],
        "apikey_txt": key_metadata(ROOT / "apikey.txt"),
    }
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
