import collections
import struct
from pathlib import Path

import unicorn
from unicorn import Uc, UcError
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
    UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
    UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12, UC_ARM_REG_SP,
)

IMAGE_BASE = 0x2000
RAM_BASE = 0x10000000
RAM_SIZE = 0x2000
STACK_TOP = 0x10000AC8
PACKET = 0x1000041C
RETURN_SENTINEL = 0x7000
IAP_ENTRY = 0x1FFF1FF0
TRANSFER = 0x267A
RGB = 0x10000552
OWNER = 0x10001910
SAVE_STATUS = 0x10001911
ACTIVE_RECIPE = 0x10001912
SELECTOR = 0x100003DC
COUNTER = 0x100003E0
ENGINE = 0x100003EC
STATE = 0x10000329
TARGET_BRIGHTNESS = 0x10000330
PENDING_BRIGHTNESS = 0x10000334

ARG_REGISTERS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
GENERAL_REGISTERS = ARG_REGISTERS + (
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
    UC_ARM_REG_R12,
)


def unpack_words(data):
    return list(struct.unpack("<" + "I" * (len(data) // 4), data))


class FirmwareHarness:
    def __init__(self, firmware):
        self.firmware = Path(firmware).resolve()
        self.image = self.firmware.read_bytes()
        self.uc = Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
        self.uc.mem_map(0, 0x10000)
        self.uc.mem_map(RAM_BASE, RAM_SIZE)
        self.uc.mem_map(0xE000E000, 0x1000)
        self.uc.mem_map(0x1FFF0000, 0x3000)
        self.uc.mem_write(IMAGE_BASE, self.image)
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._on_code)
        self.uc.hook_add(unicorn.UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        self.entry_counts = collections.Counter()
        self.invalid_accesses = []
        self.iap_commands = []
        self.eeprom_status_queues = {0x3D: [], 0x3E: []}
        self.eeprom_read_overrides = []
        self.mock_eeprom = bytearray(4096)
        self.transfers = []
        self.min_sp = STACK_TOP
        self.instruction_count = 0

    def read(self, address, size):
        return bytes(self.uc.mem_read(address, size))

    def write(self, address, data):
        self.uc.mem_write(address, bytes(data))

    def write_words(self, address, values):
        self.write(address, struct.pack("<" + "I" * len(values), *values))

    def _on_unmapped(self, uc, access, address, size, value, _user_data):
        self.invalid_accesses.append((access, address, size, value, uc.reg_read(UC_ARM_REG_PC)))
        return False

    def _return_stub(self, result):
        self.uc.reg_write(UC_ARM_REG_R0, result & 0xFFFFFFFF)
        self.uc.reg_write(UC_ARM_REG_PC, self.uc.reg_read(UC_ARM_REG_LR))

    def _mock_transfer(self):
        descriptor = self.uc.reg_read(UC_ARM_REG_R0)
        command = self.uc.reg_read(UC_ARM_REG_R1)
        source = self.uc.reg_read(UC_ARM_REG_R2)
        count = self.uc.reg_read(UC_ARM_REG_R3)
        self.transfers.append((descriptor, command, source, count, self.read(source, count)))
        self._return_stub(0)

    def _mock_iap(self):
        command_pointer = self.uc.reg_read(UC_ARM_REG_R0)
        result_pointer = self.uc.reg_read(UC_ARM_REG_R1)
        command_code = unpack_words(self.read(command_pointer, 4))[0]
        command = unpack_words(self.read(command_pointer, 20))
        status = self.eeprom_status_queues.get(command_code, []).pop(0) if self.eeprom_status_queues.get(command_code) else 0
        action = None
        if status == 0 and command_code in (0x3D, 0x3E):
            offset, ram_address, size, _clock = command[1:]
            if offset + size > len(self.mock_eeprom):
                raise RuntimeError("mock EEPROM access out of range")
            if command_code == 0x3D:
                data = self.read(ram_address, size)
                self.mock_eeprom[offset:offset + size] = data
                action = ("write", offset, data)
            else:
                data = bytes(self.mock_eeprom[offset:offset + size])
                if self.eeprom_read_overrides:
                    override = self.eeprom_read_overrides.pop(0)
                    if override is not None:
                        data = bytes(override)
                self.write(ram_address, data)
                action = ("read", offset, data)
        self.iap_commands.append({"code": command_code, "command": command, "status": status, "action": action})
        self.write_words(result_pointer, [status, 0, 0, 0])
        self._return_stub(status)

    def _on_code(self, uc, address, _size, _user_data):
        self.instruction_count += 1
        self.entry_counts[address] += 1
        self.min_sp = min(self.min_sp, uc.reg_read(UC_ARM_REG_SP))
        if address == TRANSFER:
            self._mock_transfer()
        elif address == IAP_ENTRY:
            self._mock_iap()

    def call(self, address, args=(), max_instructions=250000):
        for register in GENERAL_REGISTERS:
            self.uc.reg_write(register, 0)
        for register, value in zip(ARG_REGISTERS, args):
            self.uc.reg_write(register, value & 0xFFFFFFFF)
        self.uc.reg_write(UC_ARM_REG_SP, STACK_TOP)
        self.uc.reg_write(UC_ARM_REG_LR, RETURN_SENTINEL | 1)
        invalid_before = len(self.invalid_accesses)
        before = self.instruction_count
        try:
            self.uc.emu_start(address | 1, RETURN_SENTINEL, count=max_instructions)
        except UcError as error:
            raise RuntimeError(f"emulation failed at pc=0x{self.uc.reg_read(UC_ARM_REG_PC):08x}: {error}; invalid={self.invalid_accesses[invalid_before:]}") from error
        if len(self.invalid_accesses) != invalid_before:
            raise RuntimeError(f"unmapped access: {self.invalid_accesses[invalid_before:]}")
        pc = self.uc.reg_read(UC_ARM_REG_PC)
        if pc != RETURN_SENTINEL:
            raise RuntimeError(f"execution did not return: pc=0x{pc:08x}, expected=0x{RETURN_SENTINEL:08x}, instructions={self.instruction_count - before}")
        return {
            "r0": self.uc.reg_read(UC_ARM_REG_R0),
            "r5": self.uc.reg_read(UC_ARM_REG_R5),
            "instructions": self.instruction_count - before,
        }

    def initialize_ram(self):
        self.call(0x21D0, (0x40A0, RAM_BASE, 0x41C))
        self.write_words(0x100003F4, [48000])

    def dispatch(self, packet, pump=True, max_instructions=250000):
        assert len(packet) == 64
        self.write(PACKET, packet)
        result = self.call(0x309C, (PACKET, 64), max_instructions=max_instructions)
        main_loop = getattr(self, "main_loop", None)
        if pump and main_loop is not None:
            self.call(main_loop)
        return self.read(PACKET, 64), result

    def writes(self):
        return [entry for entry in self.iap_commands if entry["code"] == 0x3D]
