#include <stdint.h>

#define EEPROM_SLOT_A 0x100u
#define EEPROM_SLOT_B 0x140u
#define RECORD_SIZE 64u
#define RGB_SIZE 45u
#define RECORD_MAGIC 0x4c384d4du
#define RECORD_VERSION 1u
#define SEQUENCE_MASK 0x00ffffffu
#define RGB_BUFFER ((volatile uint8_t *)0x10000552u)
#define LIGHTING_STATE ((volatile uint8_t *)0x10000329u)
extern volatile uint8_t boot_status_ram[16];
extern volatile uint8_t persistent_static_ram;
#define BOOT_STATUS boot_status_ram
#define PERSISTENT_STATIC (&persistent_static_ram)

__attribute__((section(".patch_state"))) volatile uint8_t boot_status_ram[16];
__attribute__((section(".patch_state"))) volatile uint8_t persistent_static_ram;

typedef void (*light_init_fn)(void);
typedef uint32_t (*eeprom_fn)(uint32_t, void *, uint32_t);

void set_direct_mode(void);

static void stock_light_init(void)
{
    ((light_init_fn)0x3961u)();
}

static uint32_t stock_eeprom_read(uint32_t offset, void *destination, uint32_t length)
{
    return ((eeprom_fn)0x22f9u)(offset, destination, length);
}

static uint32_t stock_eeprom_write(uint32_t offset, void *source, uint32_t length)
{
    return ((eeprom_fn)0x232du)(offset, source, length);
}

static uint32_t load24(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] |
           ((uint32_t)bytes[1] << 8) |
           ((uint32_t)bytes[2] << 16);
}

static void store24(uint8_t *bytes, uint32_t value)
{
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
    bytes[2] = (uint8_t)(value >> 16);
}

static uint32_t load32(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] |
           ((uint32_t)bytes[1] << 8) |
           ((uint32_t)bytes[2] << 16) |
           ((uint32_t)bytes[3] << 24);
}

static void store32(uint8_t *bytes, uint32_t value)
{
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
    bytes[2] = (uint8_t)(value >> 16);
    bytes[3] = (uint8_t)(value >> 24);
}

static void copy_bytes(uint8_t *destination, const uint8_t *source, uint32_t length)
{
    for (uint32_t index = 0; index < length; index++)
        destination[index] = source[index];
}

static uint32_t crc32_bytes(const uint8_t *bytes, uint32_t length)
{
    uint32_t crc = 0xffffffffu;
    for (uint32_t index = 0; index < length; index++) {
        crc ^= bytes[index];
        for (uint32_t bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ (0xedb88320u & (uint32_t)-(int32_t)(crc & 1u));
    }
    return ~crc;
}

static uint32_t record_valid(const uint8_t *record)
{
    if (load32(record) != RECORD_MAGIC)
        return 0;
    if (load32(record + 4) != RECORD_VERSION)
        return 0;
    if (load32(record + 8) != RGB_SIZE)
        return 0;
    return load32(record + 60) == crc32_bytes(record, 60);
}

static uint32_t sequence_newer(uint32_t candidate, uint32_t current)
{
    uint32_t difference = (candidate - current) & SEQUENCE_MASK;
    return difference != 0 && difference < 0x800000u;
}

static uint32_t load_latest(uint8_t *record, uint32_t *latest_slot, uint32_t *latest_sequence, uint32_t *read_errors)
{
    uint8_t candidate[RECORD_SIZE] __attribute__((aligned(4)));
    uint32_t found = 0;

    *latest_slot = EEPROM_SLOT_A;
    *latest_sequence = 0;
    *read_errors = 0;
    for (uint32_t index = 0; index < 2; index++) {
        uint32_t slot = index == 0 ? EEPROM_SLOT_A : EEPROM_SLOT_B;
        if (stock_eeprom_read(slot, candidate, RECORD_SIZE) != 0) {
            *read_errors |= 1u << index;
            continue;
        }
        if (!record_valid(candidate))
            continue;
        uint32_t sequence = load24(candidate + 57);
        if (!found || sequence_newer(sequence, *latest_sequence)) {
            copy_bytes(record, candidate, RECORD_SIZE);
            *latest_slot = slot;
            *latest_sequence = sequence;
            found = 1;
        }
    }
    return found;
}

static void initialize_record(uint8_t *record, const volatile uint8_t *rgb, uint32_t sequence)
{
    for (uint32_t index = 0; index < RECORD_SIZE; index++)
        record[index] = 0;
    store32(record, RECORD_MAGIC);
    store32(record + 4, RECORD_VERSION);
    store32(record + 8, RGB_SIZE);
    copy_bytes(record + 12, (const uint8_t *)rgb, RGB_SIZE);
    store24(record + 57, sequence);
    store32(record + 60, crc32_bytes(record, 60));
}

void boot_restore(void)
{
    uint8_t record[RECORD_SIZE] __attribute__((aligned(4)));
    uint32_t slot;
    uint32_t sequence;
    uint32_t read_errors;

    for (uint32_t index = 0; index < 16; index++)
        BOOT_STATUS[index] = 0;
    BOOT_STATUS[0] = 'B';
    BOOT_STATUS[1] = 'T';
    *PERSISTENT_STATIC = 0;
    stock_light_init();
    uint32_t found = load_latest(record, &slot, &sequence, &read_errors);
    BOOT_STATUS[2] = (uint8_t)read_errors;
    BOOT_STATUS[3] = (uint8_t)found;
    store32((uint8_t *)BOOT_STATUS + 4, slot);
    store32((uint8_t *)BOOT_STATUS + 8, sequence);
    if (!found) {
        BOOT_STATUS[15] = *LIGHTING_STATE;
        return;
    }
    copy_bytes((uint8_t *)RGB_BUFFER, record + 12, RGB_SIZE);
    set_direct_mode();
    *PERSISTENT_STATIC = 1;
    copy_bytes((uint8_t *)BOOT_STATUS + 12, record + 12, 3);
    BOOT_STATUS[15] = *LIGHTING_STATE;
}

uint32_t save_current(void)
{
    uint8_t latest[RECORD_SIZE] __attribute__((aligned(4)));
    uint8_t record[RECORD_SIZE] __attribute__((aligned(4)));
    uint8_t verify[RECORD_SIZE] __attribute__((aligned(4)));
    uint32_t latest_slot;
    uint32_t latest_sequence;
    uint32_t read_errors;
    uint32_t target_slot = EEPROM_SLOT_A;
    uint32_t sequence = 1;
    uint32_t primask;
    uint32_t status;

    set_direct_mode();
    if (load_latest(latest, &latest_slot, &latest_sequence, &read_errors)) {
        target_slot = latest_slot == EEPROM_SLOT_A ? EEPROM_SLOT_B : EEPROM_SLOT_A;
        sequence = (latest_sequence + 1) & SEQUENCE_MASK;
    }
    if (read_errors != 0)
        return 0xfeu;
    initialize_record(record, RGB_BUFFER, sequence);
    __asm volatile("mrs %0, primask" : "=r"(primask));
    __asm volatile("cpsid i");
    status = stock_eeprom_write(target_slot, record, RECORD_SIZE);
    if (status == 0)
        status = stock_eeprom_read(target_slot, verify, RECORD_SIZE);
    __asm volatile("msr primask, %0" : : "r"(primask));
    if (status != 0)
        return status;
    for (uint32_t index = 0; index < RECORD_SIZE; index++) {
        if (verify[index] != record[index])
            return 0xffu;
    }
    *PERSISTENT_STATIC = 1;
    return 0;
}

void get_saved_response(uint8_t *packet)
{
    uint8_t record[RECORD_SIZE] __attribute__((aligned(4)));
    uint32_t slot;
    uint32_t sequence;
    uint32_t read_errors;
    uint32_t valid = load_latest(record, &slot, &sequence, &read_errors);

    packet[4] = (uint8_t)valid;
    for (uint32_t index = 0; index < RGB_SIZE; index++)
        packet[5 + index] = valid ? record[12 + index] : 0;
}

static void get_chip_info_response(uint8_t *packet)
{
    uint32_t command[1] __attribute__((aligned(4)));
    uint32_t result[5] __attribute__((aligned(4)));

    for (uint32_t index = 0; index < 56; index++)
        packet[5 + index] = 0;
    command[0] = 0x36;
    result[0] = 0;
    ((void (*)(uint32_t *, uint32_t *))0x1fff1ff1u)(command, result);
    packet[4] = (uint8_t)result[0];
    store32(packet + 5, result[1]);
    command[0] = 0x37;
    result[0] = 0;
    ((void (*)(uint32_t *, uint32_t *))0x1fff1ff1u)(command, result);
    packet[9] = (uint8_t)result[0];
    store32(packet + 10, result[1]);
    command[0] = 0x3a;
    result[0] = 0;
    ((void (*)(uint32_t *, uint32_t *))0x1fff1ff1u)(command, result);
    packet[14] = (uint8_t)result[0];
    for (uint32_t index = 0; index < 4; index++)
        store32(packet + 15 + index * 4, result[index + 1]);
    packet[31] = 'M';
    packet[32] = 'C';
    packet[33] = 'U';
}

void get_eeprom_dump_response(uint8_t *packet)
{
    uint8_t data[56] __attribute__((aligned(4)));
    uint32_t offset = (uint32_t)packet[2] | ((uint32_t)packet[3] << 8);
    uint32_t length = packet[4];
    uint32_t status;

    if (offset == 0xffffu && length == 0) {
        get_chip_info_response(packet);
        return;
    }
    for (uint32_t index = 0; index < 56; index++)
        packet[5 + index] = 0;
    if (length == 0 || length > 56 || offset + length > 0xfc0u) {
        packet[4] = 0xffu;
        packet[5] = 'M';
        packet[6] = 'M';
        packet[7] = '8';
        packet[8] = 'D';
        packet[9] = 1;
        copy_bytes(packet + 10, (const uint8_t *)0x4f08u, 4);
        copy_bytes(packet + 14, (const uint8_t *)BOOT_STATUS, 16);
        packet[30] = *LIGHTING_STATE;
        packet[31] = *PERSISTENT_STATIC;
        return;
    }
    status = stock_eeprom_read(offset, data, length);
    if (status == 0)
        copy_bytes(packet + 5, data, length);
    packet[4] = (uint8_t)status;
}

void get_iap_debug_response(uint8_t *packet)
{
    copy_bytes(packet + 4, (const uint8_t *)0x4f00u, 48);
    for (uint32_t index = 52; index < 64; index++)
        packet[index] = 0;
}

void set_live_color(uint8_t *data, uint32_t length)
{
    set_direct_mode();
    ((void (*)(uint8_t *, uint32_t))0x3a61u)(data, length);
}

uint32_t usb_configured(uint32_t context)
{
    if (*PERSISTENT_STATIC == 0)
        return ((uint32_t (*)(uint32_t))0x3c19u)(context);
    *(volatile uint8_t *)0x10000208u = 0;
    return 0;
}

uint32_t lighting_state_guard(uint32_t state)
{
    if (*PERSISTENT_STATIC == 0 || (state != 0 && state != 2 && state != 3 && state != 5))
        ((void (*)(uint32_t))0x39e5u)(state);
    return 0;
}

uint32_t callback_zero_guard(uint32_t context)
{
    if (*PERSISTENT_STATIC == 0)
        return ((uint32_t (*)(uint32_t))0x3c59u)(context);
    return 0;
}

uint32_t callback_two_guard(uint32_t context)
{
    if (*PERSISTENT_STATIC == 0)
        return ((uint32_t (*)(uint32_t))0x2b49u)(context);
    return 0;
}

uint32_t lighting_poll_guard(void)
{
    if (*PERSISTENT_STATIC != 0)
        return 0;
    return ((uint32_t (*)(void))0x2b9du)();
}

void set_direct_mode(void)
{
    ((void (*)(uint32_t))0x39e5u)(2);
}
