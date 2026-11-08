#!/usr/bin/env python3
import json
from pathlib import Path

CACHE_PATH = Path(__file__).resolve().parent.parent / "recovery" / "hidraw-cache.json"


def valid_interface(path):
    try:
        device = Path(path)
        uevent = Path("/sys/class/hidraw") / device.name / "device" / "uevent"
        identity = uevent.read_text()
        if "00001B1C:00001B3B" not in identity.upper():
            return False
        phys = identity.split("HID_PHYS=", 1)[1].splitlines()[0]
        return phys.endswith("/input0")
    except (OSError, IndexError):
        return False


def candidates():
    result = []
    for entry in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        path = "/dev/" + entry.name
        if valid_interface(path):
            result.append(path)
    return result


def read_record():
    try:
        record = json.loads(CACHE_PATH.read_text())
        path = record["device"]
        failures = record.get("failures", 0)
        if not valid_interface(path) or not isinstance(failures, int) or failures < 0:
            raise ValueError("invalid cache")
        return {"device": path, "failures": failures}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def read_cache():
    record = read_record()
    return record["device"] if record else None


def write_cache(path, failures=0):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CACHE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps({"device": path, "failures": failures}, indent=2) + "\n")
    temporary.replace(CACHE_PATH)


def locate():
    cached = read_cache()
    if cached:
        return cached
    found = candidates()
    if not found:
        raise RuntimeError("MM800 control interface not found")
    if len(found) != 1:
        raise RuntimeError(f"multiple MM800 control interfaces found: {found}")
    write_cache(found[0])
    return found[0]


def note_success(path):
    if read_cache() == path:
        write_cache(path, 0)


def note_failure(path):
    record = read_record()
    if not record or record["device"] != path:
        return
    failures = record["failures"] + 1
    if failures >= 3:
        CACHE_PATH.unlink(missing_ok=True)
    else:
        write_cache(path, failures)


if __name__ == "__main__":
    print(locate())
