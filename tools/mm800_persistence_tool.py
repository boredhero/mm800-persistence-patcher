#!/usr/bin/env python3
import argparse
import os
import select
import time
from pathlib import Path

from hidraw_locator import locate, note_failure, note_success
from firmware_version import load_firmware_version

PACKET_SIZE = 64
EEPROM_DUMP_SIZE = 0xFC0
DUMP_CHUNK = 56
FIRMWARE_VERSION = load_firmware_version()
EFFECT_IDS = {"breathing": 0x10, "rainbow": 0x20, "moving-rainbow": 0x30}
EFFECT_NAMES = {value: key for key, value in EFFECT_IDS.items()}
OWNER_NAMES = {0: "stock", 1: "saved-static", 2: "saved-animation", 3: "host-static", 4: "host-animation"}


class MM800:
    def __init__(self, device, timeout=2.0):
        self.timeout = timeout
        self.device = locate() if device == "auto" else device
        name = Path(self.device).name
        uevent = Path("/sys/class/hidraw") / name / "device" / "uevent"
        identity = uevent.read_text()
        if "00001B1C:00001B3B" not in identity.upper():
            raise RuntimeError(f"{self.device} is not the MM800 (1b1c:1b3b)")
        if "HID_PHYS=" not in identity or not identity.split("HID_PHYS=", 1)[1].splitlines()[0].endswith("/input0"):
            raise RuntimeError(f"{self.device} is not the MM800 control interface (/input0)")
        self.fd = os.open(self.device, os.O_RDWR | os.O_NONBLOCK)

    def close(self):
        os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, packet):
        assert len(packet) == PACKET_SIZE
        written = os.write(self.fd, packet)
        if written != PACKET_SIZE:
            raise RuntimeError(f"short HID write: {written}")

    def query(self, packet, expected_length):
        try:
            self.send(packet)
            ready, _, _ = select.select([self.fd], [], [], self.timeout)
            if not ready:
                raise TimeoutError("MM800 response timed out")
            response = os.read(self.fd, PACKET_SIZE)
            if len(response) != PACKET_SIZE:
                raise RuntimeError(f"expected padded {PACKET_SIZE}-byte response, got {len(response)}")
            if expected_length > PACKET_SIZE:
                raise ValueError("expected length exceeds packet size")
            if response[:4] != packet[:4]:
                raise RuntimeError("response header does not match request")
            note_success(self.device)
            return response
        except Exception:
            note_failure(self.device)
            raise

    def current_rgb(self):
        response = self.query(bytearray([0x0E, 0x22]) + bytes(PACKET_SIZE - 2), 49)
        return bytes(response[4:49])

    def saved_rgb(self):
        response = self.query(bytearray([0x0E, 0x23]) + bytes(PACKET_SIZE - 2), 50)
        return response[4], bytes(response[5:50])

    def iap_debug(self):
        return self.query(bytearray([0x0E, 0x60]) + bytes(PACKET_SIZE - 2), 64)

    def chip_info(self):
        return self.query(bytearray([0x0E, 0x24, 0xFF, 0xFF, 0x00]) + bytes(PACKET_SIZE - 5), 61)

    def profile(self):
        response = self.query(bytearray([0x0E, 0x25]) + bytes(PACKET_SIZE - 2), 64)
        if response[5] != 1:
            raise RuntimeError(f"unsupported effect protocol version {response[5]}; update the firmware")
        if response[10] > 45:
            raise RuntimeError("profile response has an invalid payload length")
        return {
            "status": response[4],
            "protocol": response[5],
            "capabilities": response[6],
            "owner": response[7],
            "kind": response[8],
            "effect": response[9],
            "length": response[10],
            "flags": response[11],
            "payload": bytes(response[12:12 + response[10]]),
            "last_save_status": response[57],
            "effect_ids": list(response[58:61]),
            "speed": response[61],
        }

    def capabilities(self):
        profile = self.profile()
        if profile["capabilities"] & 0x07 != 0x07:
            raise RuntimeError("installed firmware lacks the versioned static/animation preview/save capability")
        if profile["speed"] != 1:
            raise RuntimeError("installed firmware does not advertise validated speed code 1")
        return profile

    def wait_for_save(self):
        deadline = time.monotonic() + self.timeout
        while True:
            profile = self.profile()
            if profile["last_save_status"] != 0x80:
                return profile
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for verified EEPROM commit")
            time.sleep(0.01)

    def set_rgb(self, rgb):
        assert len(rgb) == 45
        packet = bytearray([0x07, 0x22, 0x0F, 0x00]) + rgb + bytes(64 - 49)
        self.send(packet)
        if self.current_rgb() != rgb:
            raise RuntimeError("live RGB readback does not match requested RGB")

    def set_effect(self, effect, color=None, persistent=False):
        effect_id, payload = encode_effect(effect, color)
        capabilities = self.capabilities()
        if effect_id not in capabilities["effect_ids"]:
            raise RuntimeError(f"installed firmware does not support effect {effect}")
        packet = bytearray([0x07, 0x25, 0xF0 if persistent else 0x00, 0x01,
                            effect_id, len(payload), 0x00]) + payload
        packet.extend(bytes(PACKET_SIZE - len(packet)))
        self.send(packet)
        if persistent:
            committed = self.wait_for_save()
            if committed["last_save_status"] != 0:
                raise RuntimeError(f"animation save failed with firmware status 0x{committed['last_save_status']:02x}")
            if (committed["status"] != 2 or committed["kind"] != 1 or
                    committed["effect"] != effect_id or committed["payload"] != payload):
                raise RuntimeError("committed animation recipe does not exactly match the requested preview parameters")
        return effect_id, payload

    def set_brightness(self, level, persistent=False):
        if level < 0 or level > 8:
            raise ValueError("brightness level must be 0–8")
        if persistent and level > 3:
            raise ValueError("persistent brightness level must be 0–3")
        selector = 0xF0 if persistent else 0x00
        self.send(bytearray([0x07, 0x05, 0x02, selector, level]) + bytes(PACKET_SIZE - 5))

    def save_current(self):
        intended = self.current_rgb()
        self.send(bytearray([0x07, 0x23]) + bytes(PACKET_SIZE - 2))
        committed = self.wait_for_save()
        if committed["last_save_status"] != 0:
            raise RuntimeError(f"static save failed with firmware status 0x{committed['last_save_status']:02x}")
        valid, saved = self.saved_rgb()
        if valid != 1 or saved != intended:
            raise RuntimeError("saved profile does not exactly match intended live RGB; validity or A/B fallback changed")

    def release_stock(self):
        self.send(bytearray([0x07, 0x04, 0x01]) + bytes(PACKET_SIZE - 3))

    def dump_eeprom(self):
        result = bytearray()
        for offset in range(0, EEPROM_DUMP_SIZE, DUMP_CHUNK):
            length = min(DUMP_CHUNK, EEPROM_DUMP_SIZE - offset)
            request = bytearray([0x0E, 0x24, offset & 0xFF, offset >> 8, length]) + bytes(PACKET_SIZE - 5)
            response = self.query(request, 61)
            if response[4] != 0:
                raise RuntimeError(f"EEPROM read failed at 0x{offset:x} with status 0x{response[4]:02x}")
            result.extend(response[5:5 + length])
        assert len(result) == EEPROM_DUMP_SIZE
        return bytes(result)


def parse_zone_rgb(text):
    if len(text) != 6:
        raise argparse.ArgumentTypeError("RGB must be six hexadecimal digits")
    try:
        return bytes.fromhex(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("RGB must be six hexadecimal digits") from error


def parse_rgb(text):
    return parse_zone_rgb(text) * 15


def encode_effect(effect, color=None):
    if effect == "breathing":
        if color is None:
            raise ValueError("breathing requires one RRGGBB color")
        if isinstance(color, str):
            color = parse_zone_rgb(color)
        payload = bytes([1]) + bytes(color)
    else:
        if color is not None:
            raise ValueError(f"{effect} does not accept a color")
        payload = bytes([1, 0]) if effect == "moving-rainbow" else bytes([1])
    return EFFECT_IDS[effect], payload


def firmware_update_warning(data):
    if bytes(data[4:12]) != b"MM8BUILD":
        return (
            "WARNING: no recognized patched-firmware build record was returned.\n"
            "If this device has stock or old firmware, update the project with "
            "`git fetch && git pull`, then run the flash wizard once."
        )
    installed_hash = bytes(data[12:44]).hex()
    if installed_hash == FIRMWARE_VERSION["embedded_build_hash"]:
        return None
    return (
        f"WARNING: installed firmware build {installed_hash} does not match firmware patch release "
        f"{FIRMWARE_VERSION['firmware_patch_version']} in this checkout.\n"
        "Update the project with: git fetch && git pull\n"
        "Then reflash once with tools/mm800_patch_and_flash.py, passing --stock-backup "
        "with the path to your original full stock backup and a new --output-dir.\n"
        "Changing colors or brightness does not require reflashing."
    )


def warn_about_firmware(mm800):
    try:
        warning = firmware_update_warning(mm800.iap_debug())
    except (OSError, RuntimeError, TimeoutError) as error:
        warning = f"WARNING: could not verify the installed firmware build: {error}"
    if warning:
        print(warning)


def print_profile(profile):
    print(f"status={profile['status']} protocol={profile['protocol']} owner={OWNER_NAMES.get(profile['owner'], 'unknown')}")
    print(f"last_save_status=0x{profile['last_save_status']:02x}")
    if profile["status"] == 1:
        print(f"kind=static rgb={profile['payload'].hex()}")
    elif profile["status"] == 2:
        name = EFFECT_NAMES.get(profile["effect"], f"unknown-0x{profile['effect']:02x}")
        print(f"kind=animation effect={name} speed={profile['payload'][0]} parameters={profile['payload'].hex()}")
    else:
        print("kind=none")


def main():
    parser = argparse.ArgumentParser(description="MM800 persistence firmware control tool; never flashes firmware")
    parser.add_argument("--device", default="auto", help="explicit /dev/hidrawN path, or 'auto' for cached MM800 control interface discovery")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("get-current")
    subparsers.add_parser("get-saved")
    subparsers.add_parser("get-profile")
    subparsers.add_parser("capabilities")
    subparsers.add_parser("iap-debug")
    subparsers.add_parser("chip-info")
    subparsers.add_parser("release", help="release runtime control to stock animation without changing EEPROM")
    set_parser = subparsers.add_parser("set-rgb", help="set all 15 zones to one color")
    set_parser.add_argument("rgb", type=parse_rgb, help="RRGGBB applied to all 15 zones; no EEPROM write")
    zones_parser = subparsers.add_parser("set-zones", help="set 15 independent zone colors")
    zones_parser.add_argument("zones", nargs=15, type=parse_zone_rgb, metavar="RRGGBB", help="colors for zones 1 through 15; no EEPROM write")
    effect_parser = subparsers.add_parser("effect", help="preview a device-run animation, or save it with --save")
    effect_parser.add_argument("effect", choices=tuple(EFFECT_IDS))
    effect_parser.add_argument("color", nargs="?", help="RRGGBB for breathing; rainbow effects take no color")
    effect_parser.add_argument("--save", action="store_true", help="explicitly write and verify this exact recipe in EEPROM")
    brightness_parser = subparsers.add_parser("brightness")
    brightness_parser.add_argument("level", type=int, help="brightness level 0–8, or 0–3 with --save")
    brightness_parser.add_argument("--save", action="store_true", help="save for future boots without changing live brightness")
    save_parser = subparsers.add_parser("save")
    save_parser.add_argument("--approve-eeprom-write", action="store_true", required=True)
    dump_parser = subparsers.add_parser("dump-eeprom")
    dump_parser.add_argument("output", type=Path, help="new output file; existing files are never overwritten")
    args = parser.parse_args()

    with MM800(args.device) as mm800:
        data = mm800.iap_debug() if args.command == "iap-debug" else None
        if data is None:
            warn_about_firmware(mm800)
        if args.command == "get-current":
            print(mm800.current_rgb().hex())
        elif args.command == "get-saved":
            valid, rgb = mm800.saved_rgb()
            print(f"valid={valid} rgb={rgb.hex()}")
        elif args.command == "get-profile":
            print_profile(mm800.profile())
        elif args.command == "capabilities":
            profile = mm800.capabilities()
            names = ", ".join(EFFECT_NAMES.get(effect, f"0x{effect:02x}") for effect in profile["effect_ids"])
            print(f"protocol={profile['protocol']} capabilities=0x{profile['capabilities']:02x}")
            print(f"effects={names} speed={profile['speed']}")
        elif args.command == "iap-debug":
            print(f"magic={bytes(data[4:12]).decode('ascii', errors='replace')}")
            print(f"embedded_build_hash={data[12:44].hex()}")
            print(f"stock_firmware_version=0x{int.from_bytes(data[44:48], 'little'):04x}")
            print(f"repository_firmware_patch_release={FIRMWARE_VERSION['firmware_patch_version']}")
            print(f"flags={int.from_bytes(data[48:52], 'little')}")
            warning = firmware_update_warning(data)
            if warning:
                print(warning)
        elif args.command == "chip-info":
            data = mm800.chip_info()
            part_id = int.from_bytes(data[5:9], "little")
            models = {
                0x00017C40: "LPC11U37/401",
                0x00007C40: "LPC11U37/501 or alternate /401",
                0x00007C44: "LPC11U37H/401",
            }
            print(f"part_status=0x{data[4]:02x} part_id=0x{part_id:08x} model={models.get(part_id, 'unknown')}")
            boot_version = int.from_bytes(data[10:14], "little")
            print(f"boot_status=0x{data[9]:02x} boot_version=0x{boot_version:08x} major={(boot_version >> 8) & 0xff} minor={boot_version & 0xff}")
            print(f"uid_status=0x{data[14]:02x} uid={data[15:31].hex()}")
        elif args.command == "set-rgb":
            mm800.set_rgb(args.rgb)
            print("live RGB verified; EEPROM unchanged")
        elif args.command == "set-zones":
            mm800.set_rgb(b"".join(args.zones))
            print("live 15-zone RGB verified; EEPROM unchanged")
        elif args.command == "effect":
            mm800.set_effect(args.effect, args.color, args.save)
            print(f"{args.effect} saved recipe verified exactly" if args.save else f"{args.effect} preview active; EEPROM unchanged")
        elif args.command == "release":
            mm800.release_stock()
            print("stock animation active; saved EEPROM profile unchanged")
        elif args.command == "brightness":
            mm800.set_brightness(args.level, args.save)
            if args.save:
                print(f"persistent brightness level {args.level} requested; live brightness unchanged")
            else:
                print(f"live brightness level {args.level} set; EEPROM unchanged")
        elif args.command == "save":
            mm800.save_current()
            print("saved RGB verified exactly; use a power cycle to test boot restore")
        elif args.command == "dump-eeprom":
            if args.output.exists():
                raise RuntimeError(f"refusing to overwrite {args.output}")
            data = mm800.dump_eeprom()
            args.output.write_bytes(data)
            print(f"wrote {len(data)} bytes to {args.output}; EEPROM unchanged")


if __name__ == "__main__":
    main()
