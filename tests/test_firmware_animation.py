import hashlib
import os
import struct
import subprocess
import unittest
import zlib
from pathlib import Path

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None

STOCK = os.environ.get("MM800_STOCK")
CANDIDATE = os.environ.get("MM800_CANDIDATE")
PATCH_ELF = os.environ.get("MM800_PATCH_ELF")
READY = bool(unicorn and STOCK and CANDIDATE and PATCH_ELF)
if READY:
    from firmware_harness import (
        ACTIVE_RECIPE, COUNTER, ENGINE, OWNER, PACKET, PENDING_BRIGHTNESS,
        RGB, SAVE_STATUS, SELECTOR, STACK_TOP, STATE, TARGET_BRIGHTNESS,
        FirmwareHarness, RETURN_SENTINEL,
    )
    from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP


def record_v1(rgb, sequence):
    record = bytearray(64)
    struct.pack_into("<III", record, 0, 0x4C384D4D, 1, 45)
    record[12:57] = rgb
    record[57] = sequence & 0xFF
    record[58] = (sequence >> 8) & 0xFF
    record[59] = (sequence >> 16) & 0xFF
    struct.pack_into("<I", record, 60, zlib.crc32(record[:60]))
    return record


def record_v2(kind, effect, payload, sequence):
    record = bytearray(64)
    struct.pack_into("<II", record, 0, 0x4C384D4D, 2)
    record[8:12] = bytes([kind, effect, len(payload), 0])
    record[12:12 + len(payload)] = payload
    record[57] = sequence & 0xFF
    record[58] = (sequence >> 8) & 0xFF
    record[59] = (sequence >> 16) & 0xFF
    struct.pack_into("<I", record, 60, zlib.crc32(record[:60]))
    return record


def effect_packet(effect, payload, save=False):
    packet = bytearray([0x07, 0x25, 0xF0 if save else 0, 1, effect, len(payload), 0]) + payload
    packet.extend(bytes(64 - len(packet)))
    return packet


def command(field, *payload):
    packet = bytearray([0x07, field]) + bytes(payload)
    packet.extend(bytes(64 - len(packet)))
    return packet


@unittest.skipUnless(READY, "set MM800_STOCK, MM800_CANDIDATE, MM800_PATCH_ELF and install unicorn")
class FinalFirmwareAnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.symbols = {}
        for line in subprocess.check_output(["llvm-nm", "-n", PATCH_ELF], text=True).splitlines():
            fields = line.split()
            if len(fields) == 3:
                cls.symbols[fields[2]] = int(fields[0], 16)
        FirmwareHarness.main_loop = cls.symbols["lighting_poll_guard"]
        globals().update({
            "ACTIVE_RECIPE": cls.symbols["active_recipe"],
            "OWNER": cls.symbols["runtime_owner_ram"],
            "SAVE_STATUS": cls.symbols["last_save_status_ram"],
        })
        stock = Path(STOCK).read_bytes()
        candidate = Path(CANDIDATE).read_bytes()
        assert hashlib.sha256(stock).hexdigest() == "5917b0de570296ba2a80cf5aa67f5bf0ef3026685453eb070364f450c3ab65fa"
        assert hashlib.sha256(candidate).hexdigest() == "07f6f7794f85ee88987de446da217209331d299ef9b80648b72b424a9a2d3e2a"
        assert candidate[0x2F00:0x2F08] == b"MM8BUILD"
        assert candidate[0x2F08:0x2F28].hex() == "cbf2708b47654f3360f01bda87e62d0636d09e78e4e47890dea248b3a901f369"

    def setUp(self):
        self.harness = FirmwareHarness(CANDIDATE)
        self.harness.initialize_ram()

    def boot(self, harness=None):
        harness = harness or self.harness
        return harness.call(self.symbols["boot_restore"])

    def reboot(self, harness):
        replacement = FirmwareHarness(CANDIDATE)
        replacement.mock_eeprom[:] = harness.mock_eeprom
        replacement.initialize_ram()
        self.boot(replacement)
        return replacement

    def test_capabilities_preview_save_and_power_loss(self):
        h = self.harness
        self.boot()
        response, _ = h.dispatch(bytearray([0x0E, 0x25]) + bytes(62))
        self.assertEqual((response[4], response[5], response[6]), (0, 1, 7))
        self.assertEqual(list(response[58:62]), [0x10, 0x20, 0x30, 1])
        preview = effect_packet(0x10, bytes([1, 0x80, 0, 0xFF]))
        save = bytearray(preview)
        save[2] = 0xF0
        self.assertEqual([index for index in range(64) if preview[index] != save[index]], [2])
        h.dispatch(preview)
        self.assertEqual(len(h.writes()), 0)
        self.assertEqual(h.read(OWNER, 1)[0], 4)
        self.assertEqual(h.read(SELECTOR, 1)[0], 0)
        engine = struct.unpack("<I", h.read(ENGINE, 4))[0]
        self.assertEqual(h.read(engine, 1)[0], 1)
        h.dispatch(save)
        self.assertEqual(len(h.writes()), 1)
        self.assertEqual(h.read(OWNER, 1)[0], 2)
        self.assertEqual(h.read(SAVE_STATUS, 1)[0], 0)
        response, _ = h.dispatch(bytearray([0x0E, 0x25]) + bytes(62))
        self.assertEqual((response[4], response[8], response[9], response[10]), (2, 1, 0x10, 4))
        self.assertEqual(response[12:16], bytes([1, 0x80, 0, 0xFF]))
        restored = self.reboot(h)
        self.assertEqual(restored.read(OWNER, 1)[0], 2)
        self.assertEqual(restored.read(SELECTOR, 1)[0], 0)
        self.assertEqual(struct.unpack("<I", restored.read(COUNTER, 4))[0], 0)
        self.assertEqual(restored.read(ACTIVE_RECIPE + 4, 4), bytes([1, 0x80, 0, 0xFF]))
        h2 = self.reboot(h)
        for _ in range(4):
            restored.call(self.symbols["lighting_poll_guard"])
            h2.call(self.symbols["lighting_poll_guard"])
        self.assertEqual(restored.read(RGB, 45), h2.read(RGB, 45))

    def test_preview_b_does_not_replace_saved_a(self):
        h = self.harness
        h.dispatch(effect_packet(0x10, bytes([1, 0x80, 0, 0xFF]), save=True))
        h.dispatch(effect_packet(0x20, bytes([1])))
        self.assertEqual(len(h.writes()), 1)
        self.assertEqual(h.read(OWNER, 1)[0], 4)
        restored = self.reboot(h)
        self.assertEqual(restored.read(ACTIVE_RECIPE + 1, 1)[0], 0x10)
        self.assertEqual(restored.read(OWNER, 1)[0], 2)

    def test_all_presets_full_cycles_and_moving_rollover(self):
        cases = [
            (0x10, bytes([1, 0xFF, 0, 0]), 0, 1, {
                0: "040000" * 15, 1: "130000" * 15, 15: "fe0000" * 15,
                30: "040000" * 15, 31: "040000" * 15, 32: "130000" * 15, 46: "fe0000" * 15,
            }),
            (0x20, bytes([1]), 1, 2, {
                0: "fe0000" * 15, 15: "fefe00" * 15, 45: "00fefe" * 15, 90: "fe0000" * 15,
            }),
            (0x30, bytes([1, 0]), 2, 3, {
                0: "fc3c00fca500eafc0082fc001afc0000fc4c00fcb500dbfc0072fc0008fc5f00fcc700fcfc00c9fc0060fc0600",
                15: "00fc4c00fcb500dbfc0072fc0008fc5f00fcc700fcfc00c9fc0060fc0600fc3700fca000effc0085fc001dfc00",
                45: "fc3700fca000effc0085fc001dfc0000fc4900fcb200defc0075fc000bfc5c00fcc400fcfc00ccfc0063fc0300",
                87: "fc3c00fca500eafc0082fc001afc0000fc4c00fcb500dbfc0072fc0008fc5f00fcc700fcfc00c9fc0060fc0600",
            }),
        ]
        for effect, payload, selector, engine_type, expected in cases:
            with self.subTest(effect=effect):
                h = FirmwareHarness(CANDIDATE)
                h.initialize_ram()
                h.call(self.symbols["boot_restore"])
                h.dispatch(effect_packet(effect, payload), pump=False)
                frames = []
                for tick in range(190):
                    h.call(self.symbols["lighting_poll_guard"])
                    if tick == 0:
                        self.assertEqual(h.read(SELECTOR, 1)[0], selector)
                        engine = struct.unpack("<I", h.read(ENGINE, 4))[0]
                        self.assertEqual(h.read(engine, 1)[0], engine_type)
                    frame = h.read(RGB, 45)
                    frames.append(frame)
                    if tick in expected:
                        self.assertEqual(frame.hex(), expected[tick], f"unexpected {effect:#x} frame at counter {tick}")
                self.assertGreater(len(set(frames)), 1)
                self.assertEqual(h.read(SELECTOR + 1, 1)[0], 3)
        h = FirmwareHarness(CANDIDATE)
        h.initialize_ram()
        h.call(self.symbols["boot_restore"])
        h.dispatch(effect_packet(0x30, bytes([1, 0])), pump=False)
        h.call(self.symbols["lighting_poll_guard"])
        initial = h.read(RGB, 45)
        for _ in range(86):
            h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual(struct.unpack("<I", h.read(COUNTER, 4))[0], 87)
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual(h.read(RGB, 45), initial)
        h.write_words(COUNTER, [4294966])
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual(h.read(RGB, 45), initial)
        self.assertEqual(struct.unpack("<I", h.read(COUNTER, 4))[0], 1)

    def test_v1_static_and_all_stock_brightness_levels(self):
        rgb = bytes(range(45))
        for brightness in range(4):
            with self.subTest(brightness=brightness):
                h = FirmwareHarness(CANDIDATE)
                h.mock_eeprom[2] = brightness
                h.mock_eeprom[0x100:0x140] = record_v1(rgb, 7)
                h.initialize_ram()
                h.call(self.symbols["boot_restore"])
                self.assertEqual(h.read(RGB, 45), rgb)
                self.assertEqual(h.read(OWNER, 1)[0], 1)
                self.assertEqual(h.read(TARGET_BRIGHTNESS, 1)[0], brightness)
                h.call(self.symbols["lighting_poll_guard"])
                self.assertEqual(h.read(RGB, 45), rgb)
                h.transfers.clear()
                h.call(0x2C08)
                self.assertEqual(len(h.transfers), 6)
        h = self.harness
        h.mock_eeprom[0x100:0x140] = record_v1(rgb, 7)
        self.boot()
        h.dispatch(command(0x23))
        self.assertEqual(h.mock_eeprom[0x100:0x104], record_v1(rgb, 7)[:4])
        self.assertEqual(struct.unpack_from("<I", h.mock_eeprom, 0x144)[0], 2)
        self.assertEqual(h.mock_eeprom[0x140 + 12:0x140 + 57], rgb)

    def test_static_packets_preview_save_and_legacy_get(self):
        h = self.harness
        rgb = bytes((index * 3) & 0xFF for index in range(45))
        h.dispatch(command(0x22, 0x0F, 0, *rgb))
        self.assertEqual(h.read(RGB, 45), rgb)
        self.assertEqual(h.read(OWNER, 1)[0], 3)
        self.assertEqual(len(h.writes()), 0)
        h.dispatch(command(0x23))
        self.assertEqual(len(h.writes()), 1)
        response, _ = h.dispatch(bytearray([0x0E, 0x23]) + bytes(62))
        self.assertEqual(response[4], 1)
        self.assertEqual(response[5:50], rgb)
        self.assertEqual(struct.unpack_from("<I", h.mock_eeprom, 0x104)[0], 2)

    def test_malformed_parameters_do_not_touch_effect_ram(self):
        h = self.harness
        h.dispatch(effect_packet(0x20, bytes([1])))
        before = h.read(0x1000037C, 0x400 - 0x37C) + h.read(0x10000590, 0x100006B9 - 0x10000590)
        owner = h.read(OWNER, 1)
        invalid = []
        invalid.append(effect_packet(0x10, bytes([0, 1, 2, 3])))
        invalid.append(effect_packet(0x11, bytes([1])))
        invalid.append(effect_packet(0x20, bytes([1, 0])))
        invalid.append(effect_packet(0x30, bytes([1, 1])))
        invalid.append(effect_packet(0x20, bytes([2])))
        packet = effect_packet(0x20, bytes([1]))
        packet[6] = 1
        invalid.append(packet)
        packet = effect_packet(0x20, bytes([1]))
        packet[20] = 1
        invalid.append(packet)
        packet = effect_packet(0x20, bytes([1]))
        packet[3] = 2
        invalid.append(packet)
        packet = effect_packet(0x20, bytes([1]))
        packet[2] = 0x80
        invalid.append(packet)
        for packet in invalid:
            with self.subTest(packet=packet[:12].hex()):
                h.dispatch(packet, pump=False)
                after = h.read(0x1000037C, 0x400 - 0x37C) + h.read(0x10000590, 0x100006B9 - 0x10000590)
                self.assertEqual(after, before)
                self.assertEqual(h.read(OWNER, 1), owner)
        self.assertEqual(len(h.writes()), 0)

    def test_corrupt_newest_and_interrupted_write_fall_back(self):
        rgb = bytes(range(45))
        old = record_v1(rgb, 5)
        for index in range(64):
            with self.subTest(corrupted_byte=index):
                newer = record_v2(1, 0x20, bytes([1]), 6)
                newer[index] ^= 1
                h = FirmwareHarness(CANDIDATE)
                h.mock_eeprom[0x100:0x140] = old
                h.mock_eeprom[0x140:0x180] = newer
                h.initialize_ram()
                h.call(self.symbols["boot_restore"])
                self.assertEqual(h.read(RGB, 45), rgb)
                self.assertEqual(h.read(OWNER, 1)[0], 1)

    def test_read_errors_and_future_records_fail_closed(self):
        for slot in range(2):
            with self.subTest(read_error_slot=slot):
                h = FirmwareHarness(CANDIDATE)
                h.mock_eeprom[0x100:0x140] = record_v1(bytes(range(45)), 5)
                h.initialize_ram()
                h.call(self.symbols["boot_restore"])
                h.eeprom_status_queues[0x3E] = [1] if slot == 0 else [0, 1]
                h.dispatch(command(0x23))
                self.assertEqual(h.read(SAVE_STATUS, 1)[0], 0xFE)
                self.assertEqual(len(h.writes()), 0)
        future = record_v1(bytes(range(45)), 8)
        struct.pack_into("<I", future, 4, 99)
        struct.pack_into("<I", future, 60, zlib.crc32(future[:60]))
        h2 = FirmwareHarness(CANDIDATE)
        h2.mock_eeprom[0x100:0x140] = future
        h2.initialize_ram()
        h2.call(self.symbols["boot_restore"])
        h2.dispatch(command(0x23))
        self.assertEqual(h2.read(SAVE_STATUS, 1)[0], 0xFD)
        self.assertEqual(len(h2.writes()), 0)

    def test_failed_readback_reports_failure(self):
        h = self.harness
        self.boot()
        h.eeprom_read_overrides = [None, None, None, bytes(64)]
        h.dispatch(command(0x23))
        self.assertEqual(h.read(SAVE_STATUS, 1)[0], 0xFF)

    def test_failed_save_preserves_previous_valid_profile(self):
        old_rgb = bytes(range(45))
        new_rgb = bytes(reversed(old_rgb))
        h = self.harness
        h.mock_eeprom[0x100:0x140] = record_v1(old_rgb, 5)
        self.boot()
        h.dispatch(command(0x22, 0x0F, 0, *new_rgb))
        h.eeprom_status_queues[0x3D] = [5]
        h.dispatch(command(0x23))
        self.assertEqual(h.read(SAVE_STATUS, 1)[0], 5)
        response, _ = h.dispatch(bytearray([0x0E, 0x23]) + bytes(62))
        self.assertEqual(response[4], 1)
        self.assertEqual(response[5:50], old_rgb)
        self.assertNotEqual(response[5:50], new_rgb)

    def test_sequence_rollover_and_mixed_versions(self):
        h = self.harness
        h.mock_eeprom[0x100:0x140] = record_v1(bytes(range(45)), 0xFFFFFF)
        h.dispatch(command(0x23))
        self.assertEqual(h.mock_eeprom[0x147], 0)
        restored = self.reboot(h)
        self.assertEqual(restored.read(OWNER, 1)[0], 1)
        h2 = FirmwareHarness(CANDIDATE)
        h2.mock_eeprom[0x100:0x140] = record_v1(bytes(range(45)), 2)
        h2.mock_eeprom[0x140:0x180] = record_v2(1, 0x20, bytes([1]), 3)
        h2.initialize_ram()
        h2.call(self.symbols["boot_restore"])
        self.assertEqual(h2.read(OWNER, 1)[0], 2)
        self.assertEqual(h2.read(ACTIVE_RECIPE + 1, 1)[0], 0x20)

    def test_suspend_resume_configure_and_host_takeover(self):
        h = self.harness
        h.mock_eeprom[2] = 3
        h.dispatch(effect_packet(0x30, bytes([1, 0]), save=True))
        h.call(self.symbols["callback_zero_guard"], (PACKET,))
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual(h.read(STATE, 1)[0], 0)
        self.assertEqual(h.read(TARGET_BRIGHTNESS, 1)[0], 0)
        self.assertEqual(h.read(OWNER, 1)[0], 2)
        h.write(PACKET + 0xED, b"\x01")
        h.call(self.symbols["usb_configured"], (PACKET,))
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual(h.read(STATE, 1)[0], 2)
        self.assertEqual(h.read(TARGET_BRIGHTNESS, 1)[0], 3)
        self.assertEqual(h.read(SELECTOR, 1)[0], 2)
        h.call(self.symbols["callback_two_guard"], (PACKET,))
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual(h.read(SELECTOR, 1)[0], 2)
        h.dispatch(command(0x04, 2))
        self.assertEqual(h.read(OWNER, 1)[0], 3)
        self.assertEqual(h.read(STATE, 1)[0], 1)
        rgb = bytes(range(45))
        h.dispatch(command(0x22, 0x0F, 0, *rgb))
        self.assertEqual(h.read(RGB, 45), rgb)
        self.assertEqual(h.read(OWNER, 1)[0], 3)
        response, _ = h.dispatch(bytearray([0x0E, 0x25]) + bytes(62))
        self.assertEqual((response[4], response[9]), (2, 0x30))
        restored = self.reboot(h)
        self.assertEqual(restored.read(OWNER, 1)[0], 2)
        restored.dispatch(command(0x04, 1))
        self.assertEqual(restored.read(OWNER, 1)[0], 0)
        response, _ = restored.dispatch(bytearray([0x0E, 0x25]) + bytes(62))
        self.assertEqual((response[4], response[9]), (2, 0x30))

    def test_static_suspend_resume_preserves_rgb(self):
        h = self.harness
        h.mock_eeprom[2] = 2
        h.mock_eeprom[0x100:0x140] = record_v1(bytes(range(45)), 1)
        h.initialize_ram()
        h.call(self.symbols["boot_restore"])
        rgb = h.read(RGB, 45)
        h.call(self.symbols["callback_zero_guard"], (PACKET,))
        h.write(PACKET + 0xED, b"\x01")
        h.call(self.symbols["usb_configured"], (PACKET,))
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual(h.read(RGB, 45), rgb)
        self.assertEqual(h.read(TARGET_BRIGHTNESS, 1)[0], 2)

    def test_stock_brightness_dispatch(self):
        h = self.harness
        h.dispatch(command(0x05, 2, 0, 3))
        self.assertEqual(h.read(TARGET_BRIGHTNESS, 1)[0], 3)
        h.dispatch(command(0x05, 2, 0, 0))
        self.assertEqual(h.read(TARGET_BRIGHTNESS, 1)[0], 0)
        h.dispatch(command(0x05, 2, 0xF0, 2))
        self.assertEqual(struct.unpack("<I", h.read(PENDING_BRIGHTNESS, 4))[0], 2)

    def test_interrupted_animation_poll_cannot_erase_queued_rgb_takeover(self):
        def rainbow_harness():
            h = FirmwareHarness(CANDIDATE)
            h.initialize_ram()
            h.dispatch(effect_packet(0x20, bytes([1])))
            return h

        h = rainbow_harness()
        writes = []
        def observe_writes(uc, access, address, size, value, user):
            if RGB <= address < RGB + 45:
                writes.append(uc.reg_read(UC_ARM_REG_PC))
        h.uc.hook_add(unicorn.UC_HOOK_MEM_WRITE, observe_writes)
        h.call(self.symbols["lighting_poll_guard"])
        self.assertTrue(writes)
        target = writes[0]

        h = rainbow_harness()
        paused = []
        def pause(uc, pc, size, user):
            if pc == target and not paused:
                paused.append(pc)
                uc.emu_stop()
        hook = h.uc.hook_add(unicorn.UC_HOOK_CODE, pause)
        h.uc.reg_write(UC_ARM_REG_SP, STACK_TOP)
        h.uc.reg_write(UC_ARM_REG_LR, RETURN_SENTINEL | 1)
        h.uc.emu_start(self.symbols["lighting_poll_guard"] | 1, RETURN_SENTINEL, count=250000)
        h.uc.hook_del(hook)
        self.assertEqual(paused, [target])
        context = h.uc.context_save()
        pc = h.uc.reg_read(UC_ARM_REG_PC)

        rgb = bytes([0x12, 0x34, 0x56]) * 15
        h.dispatch(command(0x22, 0x0F, 0, *rgb), pump=False)
        response, _ = h.dispatch(bytearray([0x0E, 0x22]) + bytes(62), pump=False)
        self.assertEqual(response[4:49], rgb)
        h.uc.context_restore(context)
        h.uc.emu_start(pc | 1, RETURN_SENTINEL, count=250000)
        self.assertEqual(h.uc.reg_read(UC_ARM_REG_PC), RETURN_SENTINEL)
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual(h.read(RGB, 45), rgb)
        self.assertEqual(h.read(OWNER, 1)[0], 3)
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual(h.read(RGB, 45), rgb)

    def test_unconfigured_resume_preserves_suspended_state(self):
        h = self.harness
        h.mock_eeprom[2] = 3
        h.dispatch(effect_packet(0x30, bytes([1, 0]), save=True))
        h.call(self.symbols["callback_zero_guard"], (PACKET,))
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual((h.read(STATE, 1)[0], h.read(TARGET_BRIGHTNESS, 1)[0]), (0, 0))
        h.write(PACKET + 0xED, b"\x00")
        h.call(self.symbols["usb_configured"], (PACKET,))
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual((h.read(STATE, 1)[0], h.read(TARGET_BRIGHTNESS, 1)[0]), (0, 0))
        h.write(PACKET + 0xED, b"\x01")
        h.call(self.symbols["usb_configured"], (PACKET,))
        h.call(self.symbols["lighting_poll_guard"])
        self.assertEqual((h.read(STATE, 1)[0], h.read(TARGET_BRIGHTNESS, 1)[0]), (2, 3))

    def test_instruction_limit_is_not_success(self):
        h = self.harness
        h.write(0x6F00, b"\xfe\xe7")
        with self.assertRaisesRegex(RuntimeError, "did not return"):
            h.call(0x6F00, max_instructions=10)

    def test_actual_msp_stack_floor_and_state_reservation(self):
        state_symbols = ["boot_status_ram", "runtime_owner_ram", "last_save_status_ram", "active_recipe", "request_queue", "request_head", "request_count"]
        addresses = sorted(self.symbols[name] for name in state_symbols)
        self.assertGreaterEqual(addresses[0], 0x10001900)
        self.assertLess(addresses[-1], 0x10001A80)
        cases = [
            ("boot", None),
            ("static-save", command(0x23)),
            ("animation-save", effect_packet(0x30, bytes([1, 0]), save=True)),
            ("animation-preview", effect_packet(0x10, bytes([1, 2, 3, 4]))),
        ]
        for name, packet in cases:
            with self.subTest(case=name):
                h = FirmwareHarness(CANDIDATE)
                h.initialize_ram()
                if packet is None:
                    h.call(self.symbols["boot_restore"])
                else:
                    h.dispatch(packet)
                self.assertGreaterEqual(h.min_sp, 0x1000076C, hex(h.min_sp))
                self.assertLessEqual(STACK_TOP - h.min_sp, 732)


if __name__ == "__main__":
    unittest.main()
