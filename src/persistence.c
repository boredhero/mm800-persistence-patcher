#include <stdint.h>

#define EEPROM_SLOT_A 0x100u
#define EEPROM_SLOT_B 0x140u
#define RECORD_SIZE 64u
#define RGB_SIZE 45u
#define RECORD_MAGIC 0x4c384d4du
#define RECORD_VERSION_1 1u
#define RECORD_VERSION_2 2u
#define SEQUENCE_MASK 0x00ffffffu
#define KIND_STATIC 0u
#define KIND_ANIMATION 1u
#define EFFECT_BREATHING 0x10u
#define EFFECT_RAINBOW 0x20u
#define EFFECT_MOVING_RAINBOW 0x30u
#define PROTOCOL_VERSION 1u
#define SPEED_CODE 1u
#define SAVE_NONE 0x7fu
#define SAVE_BUSY 0x80u
#define SAVE_INVALID 0x01u
#define SAVE_QUEUE_FULL 0x05u
#define SAVE_UNSUPPORTED_RECORD 0xfdu
#define SAVE_READ_ERROR 0xfeu
#define SAVE_VERIFY_ERROR 0xffu
#define REQUEST_STATIC_PREVIEW 0u
#define REQUEST_STATIC_SAVE 1u
#define REQUEST_EFFECT_PREVIEW 2u
#define REQUEST_EFFECT_SAVE 3u
#define REQUEST_STOCK 4u
#define REQUEST_HOST_STATIC 5u
#define REQUEST_SUSPEND 6u
#define REQUEST_RESUME 7u
#define REQUEST_CONFIGURE 8u
#define REQUEST_QUEUE_SIZE 4u
#define OWNER_STOCK 0u
#define OWNER_SAVED_STATIC 1u
#define OWNER_SAVED_ANIMATION 2u
#define OWNER_HOST_STATIC 3u
#define OWNER_HOST_ANIMATION 4u
#define RGB_BUFFER ((volatile uint8_t *)0x10000552u)
#define LIGHTING_STATE ((volatile uint8_t *)0x10000329u)
#define SELECTOR_0 ((volatile uint8_t *)0x100003dcu)
#define COUNTER_0 ((volatile uint32_t *)0x100003e0u)
#define COUNTER_1 ((volatile uint32_t *)0x100003e4u)
#define ENGINE_0 ((volatile uint32_t *)0x100003ecu)

typedef struct {
    uint8_t kind;
    uint8_t effect;
    uint8_t length;
    uint8_t flags;
    uint8_t payload[RGB_SIZE];
} Recipe;

typedef struct {
    uint32_t sequence;
    Recipe request;
} SequencedRequest;

__attribute__((section(".patch_state"))) volatile uint8_t boot_status_ram[16];
__attribute__((section(".patch_state"))) Recipe active_recipe;
__attribute__((section(".patch_state"))) SequencedRequest request_queue[REQUEST_QUEUE_SIZE];
__attribute__((section(".patch_state"))) SequencedRequest pending_rgb;
__attribute__((section(".patch_state"))) volatile uint32_t pending_mode_sequence;
__attribute__((section(".patch_state"))) volatile uint32_t lifecycle_sequence[3];
__attribute__((section(".patch_state"))) volatile uint32_t next_sequence;
__attribute__((section(".patch_state"))) volatile uint8_t pending_mode;
__attribute__((section(".patch_state"))) volatile uint8_t request_head;
__attribute__((section(".patch_state"))) volatile uint8_t request_count;
__attribute__((section(".patch_state"))) volatile uint8_t runtime_owner_ram;
__attribute__((section(".patch_state"))) volatile uint8_t last_save_status_ram;

#define BOOT_STATUS boot_status_ram
#define OWNER (&runtime_owner_ram)
#define LAST_SAVE_STATUS (&last_save_status_ram)

typedef void (*light_init_fn)(void);
typedef uint32_t (*eeprom_fn)(uint32_t, void *, uint32_t);

void set_direct_mode(void);

static void stock_light_init(void)
{
    ((light_init_fn)0x3961u)();
}

static void stock_set_state(uint32_t state)
{
    ((void (*)(uint32_t))0x39e5u)(state);
}

static void stock_select_effect(uint32_t effect, uint32_t channel)
{
    ((void (*)(uint32_t, uint32_t))0x3779u)(effect, channel);
}

static uint32_t stock_construct_effect(uint32_t constructor, void *config)
{
    return ((uint32_t (*)(uint32_t, void *))0x35fdu)(constructor, config);
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
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) | ((uint32_t)bytes[2] << 16);
}

static void store24(uint8_t *bytes, uint32_t value)
{
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
    bytes[2] = (uint8_t)(value >> 16);
}

static uint32_t load32(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
           ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
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

static uint32_t sequence_before(uint32_t candidate, uint32_t current)
{
    return candidate != 0 && (current == 0 || (int32_t)(candidate - current) < 0);
}

static uint32_t allocate_sequence(void)
{
    uint32_t primask;
    __asm volatile("mrs %0, primask" : "=r"(primask));
    __asm volatile("cpsid i");
    next_sequence++;
    if (next_sequence == 0)
        next_sequence = 1;
    uint32_t sequence = next_sequence;
    __asm volatile("msr primask, %0" : : "r"(primask));
    return sequence;
}

static uint32_t queue_request(const Recipe *request)
{
    uint32_t sequence = allocate_sequence();
    uint32_t primask;
    uint32_t status = 0;
    __asm volatile("mrs %0, primask" : "=r"(primask));
    __asm volatile("cpsid i");
    if (request_count >= REQUEST_QUEUE_SIZE) {
        status = SAVE_QUEUE_FULL;
    } else {
        uint32_t tail = (request_head + request_count) % REQUEST_QUEUE_SIZE;
        request_queue[tail].sequence = sequence;
        copy_bytes((uint8_t *)&request_queue[tail].request, (const uint8_t *)request, sizeof(Recipe));
        request_count++;
    }
    __asm volatile("msr primask, %0" : : "r"(primask));
    return status;
}

static uint32_t dequeue_request(Recipe *request)
{
    uint32_t primask;
    uint32_t best = 0;
    uint32_t source = 0xff;
    __asm volatile("mrs %0, primask" : "=r"(primask));
    __asm volatile("cpsid i");
    if (request_count != 0) {
        best = request_queue[request_head].sequence;
        source = 0;
    }
    if (sequence_before(pending_rgb.sequence, best)) {
        best = pending_rgb.sequence;
        source = 1;
    }
    if (sequence_before(pending_mode_sequence, best)) {
        best = pending_mode_sequence;
        source = 2;
    }
    for (uint32_t index = 0; index < 3; index++) {
        if (sequence_before(lifecycle_sequence[index], best)) {
            best = lifecycle_sequence[index];
            source = 3 + index;
        }
    }
    if (source == 0) {
        copy_bytes((uint8_t *)request, (const uint8_t *)&request_queue[request_head].request, sizeof(Recipe));
        request_head = (request_head + 1) % REQUEST_QUEUE_SIZE;
        request_count--;
    } else if (source == 1) {
        copy_bytes((uint8_t *)request, (const uint8_t *)&pending_rgb.request, sizeof(Recipe));
        pending_rgb.sequence = 0;
    } else if (source != 0xff) {
        for (uint32_t index = 0; index < sizeof(*request); index++)
            ((uint8_t *)request)[index] = 0;
        if (source == 2) {
            request->kind = pending_mode;
            pending_mode_sequence = 0;
        } else {
            request->kind = REQUEST_SUSPEND + source - 3;
            lifecycle_sequence[source - 3] = 0;
        }
    }
    __asm volatile("msr primask, %0" : : "r"(primask));
    return source != 0xff;
}

static void copy_logical_rgb(uint8_t *destination)
{
    uint32_t newest = 0;
    uint32_t source = 0xff;
    const uint8_t *payload = 0;
    copy_bytes(destination, (const uint8_t *)RGB_BUFFER, RGB_SIZE);
    if ((*OWNER == OWNER_SAVED_STATIC || *OWNER == OWNER_HOST_STATIC) && active_recipe.kind == KIND_STATIC)
        copy_bytes(destination, active_recipe.payload, RGB_SIZE);
    if (pending_rgb.sequence != 0) {
        newest = pending_rgb.sequence;
        source = 0;
        payload = pending_rgb.request.payload;
    }
    if (pending_mode_sequence != 0 && (newest == 0 || sequence_before(newest, pending_mode_sequence))) {
        newest = pending_mode_sequence;
        source = pending_mode == REQUEST_HOST_STATIC ? 1 : 0xff;
    }
    for (uint32_t index = 0; index < request_count; index++) {
        const SequencedRequest *request = &request_queue[(request_head + index) % REQUEST_QUEUE_SIZE];
        if (request->request.kind == REQUEST_STATIC_SAVE &&
            (newest == 0 || sequence_before(newest, request->sequence))) {
            newest = request->sequence;
            source = 0;
            payload = request->request.payload;
        }
    }
    if (source == 0)
        copy_bytes(destination, payload, RGB_SIZE);
    if (source == 1)
        for (uint32_t channel = 0; channel < RGB_SIZE; channel++)
            destination[channel] = 0;
}

static uint32_t save_pending(void)
{
    for (uint32_t index = 0; index < request_count; index++) {
        uint8_t kind = request_queue[(request_head + index) % REQUEST_QUEUE_SIZE].request.kind;
        if (kind == REQUEST_STATIC_SAVE || kind == REQUEST_EFFECT_SAVE)
            return 1;
    }
    return 0;
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

static uint32_t effect_length(uint8_t effect)
{
    if (effect == EFFECT_BREATHING)
        return 4;
    if (effect == EFFECT_RAINBOW)
        return 1;
    if (effect == EFFECT_MOVING_RAINBOW)
        return 2;
    return 0;
}

static uint32_t recipe_valid(uint8_t kind, uint8_t effect, uint8_t length, uint8_t flags, const uint8_t *payload)
{
    if (flags != 0)
        return 0;
    if (kind == KIND_STATIC)
        return effect == 0 && length == RGB_SIZE;
    if (kind != KIND_ANIMATION || length != effect_length(effect) || payload[0] != SPEED_CODE)
        return 0;
    return effect != EFFECT_MOVING_RAINBOW || payload[1] == 0;
}

static uint32_t sequence_newer(uint32_t candidate, uint32_t current)
{
    uint32_t difference = (candidate - current) & SEQUENCE_MASK;
    return difference != 0 && difference < 0x800000u;
}

static uint32_t record_status(const uint8_t *record)
{
    uint32_t version;
    if (load32(record) != RECORD_MAGIC || load32(record + 60) != crc32_bytes(record, 60))
        return 0;
    version = load32(record + 4);
    if (version == RECORD_VERSION_1)
        return load32(record + 8) == RGB_SIZE ? 1 : 2;
    if (version != RECORD_VERSION_2)
        return 2;
    if (!recipe_valid(record[8], record[9], record[10], record[11], record + 12))
        return 2;
    for (uint32_t index = record[10]; index < RGB_SIZE; index++) {
        if (record[12 + index] != 0)
            return 2;
    }
    return 1;
}

static uint32_t load_latest(uint8_t *record, uint32_t *latest_slot, uint32_t *latest_sequence,
                            uint32_t *read_errors, uint32_t *unsupported)
{
    uint8_t candidate[RECORD_SIZE] __attribute__((aligned(4)));
    uint32_t found = 0;
    *latest_slot = EEPROM_SLOT_A;
    *latest_sequence = 0;
    *read_errors = 0;
    *unsupported = 0;
    for (uint32_t index = 0; index < 2; index++) {
        uint32_t slot = index == 0 ? EEPROM_SLOT_A : EEPROM_SLOT_B;
        uint32_t status;
        if (stock_eeprom_read(slot, candidate, RECORD_SIZE) != 0) {
            *read_errors |= 1u << index;
            continue;
        }
        status = record_status(candidate);
        if (status == 2) {
            *unsupported |= 1u << index;
            continue;
        }
        if (status != 1)
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

static void set_active_static(const volatile uint8_t *rgb)
{
    active_recipe.kind = KIND_STATIC;
    active_recipe.effect = 0;
    active_recipe.length = RGB_SIZE;
    active_recipe.flags = 0;
    copy_bytes(active_recipe.payload, (const uint8_t *)rgb, RGB_SIZE);
}

static void set_active_animation(uint8_t effect, uint8_t length, const uint8_t *payload)
{
    active_recipe.kind = KIND_ANIMATION;
    active_recipe.effect = effect;
    active_recipe.length = length;
    active_recipe.flags = 0;
    copy_bytes(active_recipe.payload, payload, length);
    for (uint32_t index = length; index < RGB_SIZE; index++)
        active_recipe.payload[index] = 0;
}

static void apply_active_animation(uint8_t owner)
{
    uint8_t config[11] __attribute__((aligned(4)));
    uint32_t constructor;
    uint32_t selector;
    uint32_t engine;
    for (uint32_t index = 0; index < 11; index++)
        config[index] = 0;
    config[2] = SPEED_CODE;
    config[6] = 255;
    config[10] = 255;
    if (active_recipe.effect == EFFECT_BREATHING) {
        constructor = 1;
        selector = 0;
        copy_bytes(config + 3, active_recipe.payload + 1, 3);
    } else if (active_recipe.effect == EFFECT_RAINBOW) {
        constructor = 2;
        selector = 1;
    } else {
        constructor = 3;
        selector = 2;
    }
    set_direct_mode();
    stock_select_effect(3, 1);
    *COUNTER_0 = 0;
    *COUNTER_1 = 0;
    engine = stock_construct_effect(constructor, config);
    if (engine == 0)
        return;
    *ENGINE_0 = engine;
    *SELECTOR_0 = (uint8_t)selector;
    *OWNER = owner;
}

static void activate_static(const volatile uint8_t *rgb, uint8_t owner)
{
    set_direct_mode();
    set_active_static(rgb);
    *OWNER = owner;
}

void boot_restore(void)
{
    uint8_t record[RECORD_SIZE] __attribute__((aligned(4)));
    uint32_t slot;
    uint32_t sequence;
    uint32_t read_errors;
    uint32_t unsupported;
    for (uint32_t index = 0; index < 16; index++)
        BOOT_STATUS[index] = 0;
    BOOT_STATUS[0] = 'B';
    BOOT_STATUS[1] = 'T';
    *OWNER = OWNER_STOCK;
    *LAST_SAVE_STATUS = SAVE_NONE;
    request_head = 0;
    request_count = 0;
    pending_rgb.sequence = 0;
    pending_mode_sequence = 0;
    next_sequence = 0;
    for (uint32_t index = 0; index < 3; index++)
        lifecycle_sequence[index] = 0;
    stock_light_init();
    uint32_t found = load_latest(record, &slot, &sequence, &read_errors, &unsupported);
    BOOT_STATUS[2] = (uint8_t)read_errors;
    BOOT_STATUS[3] = (uint8_t)found;
    store32((uint8_t *)BOOT_STATUS + 4, slot);
    store32((uint8_t *)BOOT_STATUS + 8, sequence);
    if (!found) {
        BOOT_STATUS[15] = *LIGHTING_STATE;
        return;
    }
    if (load32(record + 4) == RECORD_VERSION_1 || record[8] == KIND_STATIC) {
        copy_bytes((uint8_t *)RGB_BUFFER, record + 12, RGB_SIZE);
        activate_static(RGB_BUFFER, OWNER_SAVED_STATIC);
        copy_bytes((uint8_t *)BOOT_STATUS + 12, record + 12, 3);
    } else {
        set_active_animation(record[9], record[10], record + 12);
        apply_active_animation(OWNER_SAVED_ANIMATION);
        copy_bytes((uint8_t *)BOOT_STATUS + 12, active_recipe.payload, 3);
    }
    BOOT_STATUS[15] = *LIGHTING_STATE;
}

static uint32_t commit_active_recipe(void)
{
    uint8_t latest[RECORD_SIZE] __attribute__((aligned(4)));
    uint8_t record[RECORD_SIZE] __attribute__((aligned(4)));
    uint8_t verify[RECORD_SIZE] __attribute__((aligned(4)));
    uint32_t latest_slot;
    uint32_t latest_sequence;
    uint32_t read_errors;
    uint32_t unsupported;
    uint32_t target_slot = EEPROM_SLOT_A;
    uint32_t sequence = 1;
    uint32_t primask;
    uint32_t status;
    if (load_latest(latest, &latest_slot, &latest_sequence, &read_errors, &unsupported)) {
        target_slot = latest_slot == EEPROM_SLOT_A ? EEPROM_SLOT_B : EEPROM_SLOT_A;
        sequence = (latest_sequence + 1) & SEQUENCE_MASK;
    }
    if (read_errors != 0)
        return SAVE_READ_ERROR;
    if (unsupported != 0)
        return SAVE_UNSUPPORTED_RECORD;
    for (uint32_t index = 0; index < RECORD_SIZE; index++)
        record[index] = 0;
    store32(record, RECORD_MAGIC);
    store32(record + 4, RECORD_VERSION_2);
    record[8] = active_recipe.kind;
    record[9] = active_recipe.effect;
    record[10] = active_recipe.length;
    record[11] = active_recipe.flags;
    copy_bytes(record + 12, active_recipe.payload, RGB_SIZE);
    store24(record + 57, sequence);
    store32(record + 60, crc32_bytes(record, 60));
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
            return SAVE_VERIFY_ERROR;
    }
    return 0;
}

static void process_requests(void)
{
    Recipe request;
    while (dequeue_request(&request)) {
        if (request.kind == REQUEST_STATIC_PREVIEW || request.kind == REQUEST_STATIC_SAVE) {
            uint32_t status = 0;
            set_active_static(request.payload);
            set_direct_mode();
            *OWNER = OWNER_HOST_STATIC;
            copy_bytes((uint8_t *)RGB_BUFFER, request.payload, RGB_SIZE);
            if (request.kind == REQUEST_STATIC_SAVE) {
                status = commit_active_recipe();
                *LAST_SAVE_STATUS = (uint8_t)status;
                if (status == 0)
                    *OWNER = OWNER_SAVED_STATIC;
            }
        } else if (request.kind == REQUEST_EFFECT_PREVIEW || request.kind == REQUEST_EFFECT_SAVE) {
            uint32_t status = 0;
            set_active_animation(request.effect, request.length, request.payload);
            apply_active_animation(OWNER_HOST_ANIMATION);
            if (request.kind == REQUEST_EFFECT_SAVE) {
                status = commit_active_recipe();
                *LAST_SAVE_STATUS = (uint8_t)status;
                if (status == 0)
                    *OWNER = OWNER_SAVED_ANIMATION;
            }
        } else if (request.kind == REQUEST_STOCK) {
            *OWNER = OWNER_STOCK;
            stock_set_state(2);
            stock_select_effect(2, 0);
        } else if (request.kind == REQUEST_HOST_STATIC) {
            stock_set_state(1);
            set_active_static(RGB_BUFFER);
            *OWNER = OWNER_HOST_STATIC;
        } else if (request.kind == REQUEST_SUSPEND) {
            stock_set_state(0);
        } else {
            stock_set_state(2);
            if (*OWNER == OWNER_SAVED_ANIMATION || *OWNER == OWNER_HOST_ANIMATION)
                apply_active_animation(*OWNER);
        }
    }
}

uint32_t save_current(void)
{
    Recipe request;
    uint32_t status;
    for (uint32_t index = 0; index < sizeof(request); index++)
        ((uint8_t *)&request)[index] = 0;
    request.kind = REQUEST_STATIC_SAVE;
    request.length = RGB_SIZE;
    copy_logical_rgb(request.payload);
    status = queue_request(&request);
    *LAST_SAVE_STATUS = status == 0 ? SAVE_BUSY : (uint8_t)status;
    return status;
}

uint32_t set_effect_recipe(uint8_t *packet, uint32_t length)
{
    Recipe request;
    uint32_t status = SAVE_INVALID;
    uint8_t effect = packet[4];
    uint8_t payload_length = packet[5];
    if (length != RECORD_SIZE - 4 || (packet[2] != 0 && packet[2] != 0xf0) ||
        packet[3] != PROTOCOL_VERSION ||
        !recipe_valid(KIND_ANIMATION, effect, payload_length, packet[6], packet + 7))
        goto out;
    for (uint32_t index = 7 + payload_length; index < RECORD_SIZE; index++) {
        if (packet[index] != 0)
            goto out;
    }
    for (uint32_t index = 0; index < sizeof(request); index++)
        ((uint8_t *)&request)[index] = 0;
    request.kind = packet[2] == 0xf0 ? REQUEST_EFFECT_SAVE : REQUEST_EFFECT_PREVIEW;
    request.effect = effect;
    request.length = payload_length;
    copy_bytes(request.payload, packet + 7, payload_length);
    status = queue_request(&request);
out:
    if (packet[2] == 0xf0)
        *LAST_SAVE_STATUS = status == 0 ? SAVE_BUSY : (uint8_t)status;
    return status;
}

static uint32_t profile_from_record(uint8_t *packet, const uint8_t *record)
{
    if (load32(record + 4) == RECORD_VERSION_1) {
        packet[8] = KIND_STATIC;
        packet[9] = 0;
        packet[10] = RGB_SIZE;
        packet[11] = 0;
    } else {
        copy_bytes(packet + 8, record + 8, 4);
    }
    copy_bytes(packet + 12, record + 12, RGB_SIZE);
    return record[8] == KIND_ANIMATION && load32(record + 4) != RECORD_VERSION_1 ? 2 : 1;
}

void get_saved_response(uint8_t *packet)
{
    uint8_t record[RECORD_SIZE] __attribute__((aligned(4)));
    uint32_t slot;
    uint32_t sequence;
    uint32_t read_errors;
    uint32_t unsupported;
    uint32_t found = load_latest(record, &slot, &sequence, &read_errors, &unsupported);
    uint32_t kind = found ? profile_from_record(packet, record) : 0;
    packet[4] = (uint8_t)kind;
    if (kind != 1) {
        for (uint32_t index = 0; index < RGB_SIZE; index++)
            packet[5 + index] = 0;
    } else {
        copy_bytes(packet + 5, packet + 12, RGB_SIZE);
    }
}

void get_current_response(uint8_t *packet)
{
    copy_logical_rgb(packet + 4);
}

void get_profile_response(uint8_t *packet)
{
    uint8_t record[RECORD_SIZE] __attribute__((aligned(4)));
    uint32_t slot;
    uint32_t sequence;
    uint32_t read_errors;
    uint32_t unsupported;
    uint32_t found;
    for (uint32_t index = 4; index < RECORD_SIZE; index++)
        packet[index] = 0;
    found = load_latest(record, &slot, &sequence, &read_errors, &unsupported);
    packet[4] = found ? (uint8_t)profile_from_record(packet, record) :
                  (read_errors ? SAVE_READ_ERROR : (unsupported ? SAVE_UNSUPPORTED_RECORD : 0));
    packet[5] = PROTOCOL_VERSION;
    packet[6] = 0x07;
    packet[7] = *OWNER;
    packet[57] = save_pending() ? SAVE_BUSY : *LAST_SAVE_STATUS;
    packet[58] = EFFECT_BREATHING;
    packet[59] = EFFECT_RAINBOW;
    packet[60] = EFFECT_MOVING_RAINBOW;
    packet[61] = SPEED_CODE;
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
        packet[9] = 2;
        copy_bytes(packet + 10, (const uint8_t *)0x4f08u, 4);
        copy_bytes(packet + 14, (const uint8_t *)BOOT_STATUS, 16);
        packet[30] = *LIGHTING_STATE;
        packet[31] = *OWNER;
        return;
    }
    status = stock_eeprom_read(offset, data, length);
    if (status == 0)
        copy_bytes(packet + 5, data, length);
    packet[4] = (uint8_t)status;
}

void get_iap_debug_response(uint8_t *packet)
{
    copy_bytes(packet + 4, (const uint8_t *)0x5f00u, 48);
    for (uint32_t index = 52; index < 64; index++)
        packet[index] = 0;
}

static uint32_t queue_lifecycle(uint8_t kind)
{
    uint32_t sequence = allocate_sequence();
    uint32_t primask;
    __asm volatile("mrs %0, primask" : "=r"(primask));
    __asm volatile("cpsid i");
    lifecycle_sequence[kind - REQUEST_SUSPEND] = sequence;
    __asm volatile("msr primask, %0" : : "r"(primask));
    return 0;
}

void set_live_color(uint8_t *data, uint32_t length)
{
    Recipe request;
    uint32_t primask;
    for (uint32_t index = 0; index < sizeof(request); index++)
        ((uint8_t *)&request)[index] = 0;
    request.kind = REQUEST_STATIC_PREVIEW;
    request.length = RGB_SIZE;
    copy_logical_rgb(request.payload);
    if (length > RGB_SIZE)
        length = RGB_SIZE;
    copy_bytes(request.payload, data, length);
    uint32_t sequence = allocate_sequence();
    __asm volatile("mrs %0, primask" : "=r"(primask));
    __asm volatile("cpsid i");
    copy_bytes((uint8_t *)&pending_rgb.request, (const uint8_t *)&request, sizeof(Recipe));
    pending_rgb.sequence = sequence;
    __asm volatile("msr primask, %0" : : "r"(primask));
}

void set_stock_mode(uint8_t *packet)
{
    uint32_t sequence = allocate_sequence();
    uint32_t primask;
    __asm volatile("mrs %0, primask" : "=r"(primask));
    __asm volatile("cpsid i");
    pending_mode = packet[2] == 1 ? REQUEST_STOCK : REQUEST_HOST_STATIC;
    pending_mode_sequence = sequence;
    __asm volatile("msr primask, %0" : : "r"(primask));
}

uint32_t usb_configured(uint32_t context)
{
    *(volatile uint8_t *)0x10000208u = 0;
    if (*(volatile uint8_t *)(context + 0xed) != 0)
        return queue_lifecycle(REQUEST_RESUME);
    return 0;
}

uint32_t lighting_state_guard(uint32_t state)
{
    if (*OWNER == OWNER_STOCK || state == 0) {
        stock_set_state(state);
    } else if (state == 2) {
        stock_set_state(state);
        if (*OWNER == OWNER_SAVED_ANIMATION || *OWNER == OWNER_HOST_ANIMATION)
            apply_active_animation(*OWNER);
    }
    return 0;
}

uint32_t callback_zero_guard(uint32_t context)
{
    (void)context;
    return queue_lifecycle(REQUEST_SUSPEND);
}

uint32_t callback_two_guard(uint32_t context)
{
    (void)context;
    return queue_lifecycle(REQUEST_CONFIGURE);
}

uint32_t lighting_poll_guard(void)
{
    process_requests();
    if (*OWNER == OWNER_SAVED_STATIC || *OWNER == OWNER_HOST_STATIC)
        return 0;
    if ((*OWNER == OWNER_SAVED_ANIMATION || *OWNER == OWNER_HOST_ANIMATION) &&
        active_recipe.effect == EFFECT_MOVING_RAINBOW && *COUNTER_0 >= 87)
        *COUNTER_0 = 0;
    return ((uint32_t (*)(void))0x2b9du)();
}

void set_direct_mode(void)
{
    stock_set_state(2);
}
