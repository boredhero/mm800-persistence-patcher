from pathlib import Path


VERSION_PATH = Path(__file__).resolve().parents[1] / "version.yml"


def load_firmware_version():
    values = {}
    for line in VERSION_PATH.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        key, separator, value = line.partition(":")
        if not separator or key not in {"firmware_patch_version", "embedded_build_hash"} or key in values:
            raise RuntimeError(f"invalid firmware version entry: {line}")
        values[key] = value.strip()
    if set(values) != {"firmware_patch_version", "embedded_build_hash"}:
        raise RuntimeError("version.yml must define firmware_patch_version and embedded_build_hash")
    try:
        version = int(values["firmware_patch_version"], 10)
        bytes.fromhex(values["embedded_build_hash"])
    except ValueError as error:
        raise RuntimeError("invalid firmware release number or build hash in version.yml") from error
    if version < 1 or len(values["embedded_build_hash"]) != 64:
        raise RuntimeError("invalid firmware release number or build hash in version.yml")
    return {"firmware_patch_version": version, "embedded_build_hash": values["embedded_build_hash"]}
