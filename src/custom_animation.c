#include "custom_animation.h"

#define CUSTOM_MAGIC 0x42384d4du
#define CUSTOM_HEADER_SIZE 32u
#define CUSTOM_STATE_EMPTY 0u
#define CUSTOM_STATE_UPLOADING 1u
#define CUSTOM_STATE_VALID 2u
#define CUSTOM_LOOP 1u
#define CUSTOM_END_OFF 2u
#define CUSTOM_RGB ((volatile uint8_t *)0x10000552u)
#define GAIN_SCALE 0xffffffffu

extern volatile uint8_t runtime_owner_ram;
void set_direct_mode(void);

typedef struct {
    uint8_t codec;
    uint8_t state;
    uint16_t bank;
    uint16_t total_size;
    uint16_t palette_count;
    uint16_t frame_count;
    uint16_t timeline_count;
    uint16_t initial;
    uint16_t palette_bytes;
    uint16_t frame_bytes;
    uint16_t timeline_bytes;
    uint16_t index;
    uint8_t flags;
    uint16_t global_gain;
    uint32_t generation;
    uint32_t upload_offset;
    uint8_t last_status;
    uint32_t remaining;
    uint16_t delta_offset;
    volatile uint8_t decoding;
} CustomState;

__attribute__((section(".patch_state"))) CustomState custom_state;
__attribute__((section(".patch_state"))) uint8_t custom_scratch[45];

static uint32_t eeprom_read(uint32_t offset, void *destination, uint32_t length)
{
    return ((uint32_t (*)(uint32_t, void *, uint32_t))0x22f9u)(offset, destination, length);
}

static uint32_t eeprom_write(uint32_t offset, void *source, uint32_t length)
{
    return ((uint32_t (*)(uint32_t, void *, uint32_t))0x232du)(offset, source, length);
}

static uint32_t load32(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
           ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static uint32_t load16(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8);
}

static void store16(uint8_t *bytes, uint32_t value)
{
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
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

static uint32_t crc32_eeprom(uint32_t offset, uint32_t length, uint32_t *checksum)
{
    uint8_t block[32] __attribute__((aligned(4)));
    uint32_t crc = 0xffffffffu;
    for (uint32_t base = 0; base < length; base += 32) {
        uint32_t count = length - base < 32 ? length - base : 32;
        if (eeprom_read(offset + base, block, count) != 0)
            return 0;
        for (uint32_t index = 0; index < count; index++) {
            uint8_t value = block[index];
            if (base + index >= 28 && base + index < CUSTOM_HEADER_SIZE)
                value = 0;
            crc ^= value;
            for (uint32_t bit = 0; bit < 8; bit++)
                crc = (crc >> 1) ^ (0xedb88320u & (uint32_t)-(int32_t)(crc & 1u));
        }
    }
    *checksum = ~crc;
    return 1;
}

static uint32_t read_bank_header(uint32_t bank, uint8_t *header)
{
    return eeprom_read(bank, header, CUSTOM_BANK_HEADER) == 0;
}

static uint32_t bank_valid(uint32_t bank, uint32_t *generation)
{
    uint8_t header[CUSTOM_BANK_HEADER] __attribute__((aligned(4)));
    if (!read_bank_header(bank, header))
        return 0;
    if (load32(header) != CUSTOM_MAGIC || load16(header + 4) != 1 || load16(header + 6) != CUSTOM_STATE_VALID)
        return 0;
    if (load16(header + 12) < CUSTOM_HEADER_SIZE || load16(header + 12) > CUSTOM_PAYLOAD_MAX ||
        load32(header + 60) != crc32_bytes(header, 60))
        return 0;
    *generation = load32(header + 8);
    return 1;
}

static uint32_t payload_address(void)
{
    return custom_state.bank + CUSTOM_BANK_HEADER;
}

static uint32_t timeline_address(void)
{
    return payload_address() + CUSTOM_HEADER_SIZE + custom_state.palette_bytes + custom_state.frame_bytes;
}

static uint32_t decode_header_at(uint32_t address)
{
    uint8_t header[CUSTOM_HEADER_SIZE] __attribute__((aligned(4)));
    if (eeprom_read(address, header, CUSTOM_HEADER_SIZE) != 0)
        return 0;
    if (load32(header) != 0x41384d4du || header[4] != 1 || header[5] < 1 || header[5] > 3)
        return 0;
    uint32_t total_size = load16(header + 10);
    if (load16(header + 8) != CUSTOM_HEADER_SIZE || total_size < CUSTOM_HEADER_SIZE || total_size > CUSTOM_PAYLOAD_MAX)
        return 0;
    if ((header[6] & ~3) || (header[6] & 1 && header[6] & 2) || (header[5] != 3 && load16(header + 26)))
        return 0;
    if (header[7] != 0 && header[7] != 4 && header[7] != 8)
        return 0;
    uint32_t palette_count = load16(header + 12);
    if ((header[7] == 0 && palette_count) || (header[7] && !palette_count))
        return 0;
    if ((header[7] == 4 && palette_count > 16) || (header[7] == 8 && (!palette_count || palette_count > 256)))
        return 0;
    if (load16(header + 20) != palette_count * 3)
        return 0;
    uint32_t computed_crc;
    if (!crc32_eeprom(address, total_size, &computed_crc) || computed_crc != load32(header + 28))
        return 0;
    custom_state.total_size = total_size;
    custom_state.flags = header[6];
    custom_state.codec = header[5];
    custom_state.global_gain = header[5] == 3 ? load16(header + 26) : 65535;
    custom_state.palette_count = palette_count;
    custom_state.frame_count = load16(header + 14);
    custom_state.timeline_count = load16(header + 16);
    custom_state.initial = load16(header + 18);
    custom_state.palette_bytes = load16(header + 20);
    custom_state.frame_bytes = load16(header + 22);
    custom_state.timeline_bytes = load16(header + 24);
    if (!custom_state.timeline_count ||
        custom_state.palette_bytes + custom_state.frame_bytes + custom_state.timeline_bytes + CUSTOM_HEADER_SIZE != total_size)
        return 0;
    uint32_t stride = header[7] == 0 ? 45 : (header[7] == 4 ? 8 : 15);
    if (custom_state.codec == 1 &&
        (!custom_state.frame_count || custom_state.initial >= custom_state.frame_count ||
         custom_state.frame_bytes != custom_state.frame_count * stride ||
         custom_state.timeline_bytes != custom_state.timeline_count * 6))
        return 0;
    if (custom_state.codec == 2 && (custom_state.frame_count || custom_state.initial || custom_state.frame_bytes))
        return 0;
    if (custom_state.codec == 3 &&
        (!custom_state.frame_count || custom_state.frame_count > 15 || !custom_state.initial || !custom_state.palette_count ||
         custom_state.frame_bytes != custom_state.frame_count * 6 ||
         custom_state.timeline_bytes != custom_state.timeline_count * 6))
        return 0;
    return 1;
}

static uint32_t palette_color(uint32_t index, uint8_t *output)
{
    if (index >= custom_state.palette_count)
        return 0;
    return eeprom_read(payload_address() + CUSTOM_HEADER_SIZE + index * 3, output, 3) == 0;
}

static uint32_t packed_index(uint32_t address, uint32_t width, uint32_t index, uint32_t count, uint32_t *value)
{
    uint8_t byte;
    if (index >= count)
        return 0;
    if (width == 8) {
        if (eeprom_read(address + index, &byte, 1) != 0)
            return 0;
        *value = byte;
        return 1;
    }
    if (eeprom_read(address + index / 2, &byte, 1) != 0)
        return 0;
    if ((count & 1) && index + 1 == count && (byte & 0xf0))
        return 0;
    *value = (index & 1) ? byte >> 4 : byte & 15;
    return 1;
}

static uint32_t packed_frame(uint32_t address, uint32_t width, uint8_t *output)
{
    for (uint32_t zone = 0; zone < 15; zone++) {
        uint32_t index;
        if (!packed_index(address, width, zone, 15, &index))
            return 0;
        if (!palette_color(index, output + zone * 3))
            return 0;
    }
    return 1;
}

static uint32_t raw_frame(uint32_t address, uint8_t *output)
{
    return eeprom_read(address, output, 45) == 0;
}

static uint32_t dictionary_entry(uint8_t *output)
{
    uint8_t entry[6] __attribute__((aligned(4)));
    uint32_t address = timeline_address() + custom_state.index * 6;
    if (eeprom_read(address, entry, 6) != 0 || load32(entry + 2) == 0)
        return 0;
    uint32_t frame_id = load16(entry);
    uint32_t width = custom_state.palette_count ? (custom_state.palette_count <= 16 ? 4 : 8) : 0;
    uint32_t stride = width == 0 ? 45 : (width == 4 ? 8 : 15);
    if (frame_id >= custom_state.frame_count || (frame_id + 1) * stride > custom_state.frame_bytes ||
        (custom_state.index == 0 && frame_id != custom_state.initial))
        return 0;
    uint32_t address_frame = payload_address() + CUSTOM_HEADER_SIZE + custom_state.palette_bytes + frame_id * stride;
    if (!(width == 0 ? raw_frame(address_frame, output) : packed_frame(address_frame, width, output)))
        return 0;
    custom_state.remaining = load32(entry + 2);
    return 1;
}

static uint32_t delta_entry(uint8_t *output)
{
    uint8_t header[8] __attribute__((aligned(4)));
    if (custom_state.delta_offset > custom_state.timeline_bytes ||
        custom_state.timeline_bytes - custom_state.delta_offset < 5)
        return 0;
    uint32_t address = timeline_address() + custom_state.delta_offset;
    if (eeprom_read(address, header, 5) != 0 || load32(header + 1) == 0)
        return 0;
    uint32_t kind = header[0];
    uint32_t width = custom_state.palette_count ? (custom_state.palette_count <= 16 ? 4 : 8) : 0;
    uint32_t next;
    if (kind == 0 || kind == 2) {
        uint32_t stride = kind == 0 ? 45 : (width == 4 ? 8 : 15);
        if ((kind == 0) != (width == 0))
            return 0;
        next = 5 + stride;
        if (next > custom_state.timeline_bytes - custom_state.delta_offset)
            return 0;
        if (kind == 0) {
            if (!raw_frame(address + 5, output))
                return 0;
        } else if (!packed_frame(address + 5, width, output)) {
            return 0;
        }
    } else if (kind == 1 || kind == 3) {
        if ((kind == 1) != (width == 0) || custom_state.index == 0 ||
            custom_state.timeline_bytes - custom_state.delta_offset < 8)
            return 0;
        if (eeprom_read(address + 5, header + 5, 3) != 0)
            return 0;
        uint32_t mask = load16(header + 5);
        uint32_t count = header[7];
        if (mask & 0x8000 || count > 15)
            return 0;
        uint32_t bits = 0;
        for (uint32_t zone = 0; zone < 15; zone++)
            if (mask & (1u << zone))
                bits++;
        if (bits != count)
            return 0;
        uint32_t replacement_bytes = width == 0 ? count * 3 : (width == 8 ? count : (count + 1) / 2);
        next = 8 + replacement_bytes;
        if (next > custom_state.timeline_bytes - custom_state.delta_offset)
            return 0;
        uint32_t replacement_index = 0;
        for (uint32_t zone = 0; zone < 15; zone++) {
            if (!(mask & (1u << zone)))
                continue;
            if (width == 0) {
                if (eeprom_read(address + 8 + replacement_index * 3, output + zone * 3, 3) != 0)
                    return 0;
            } else {
                uint32_t color_index;
                if (!packed_index(address + 8, width, replacement_index, count, &color_index))
                    return 0;
                if (!palette_color(color_index, output + zone * 3))
                    return 0;
            }
            replacement_index++;
        }
    } else {
        return 0;
    }
    custom_state.delta_offset += next;
    custom_state.remaining = load32(header + 1);
    return 1;
}

static uint32_t multiply_16_by_32(uint32_t factor, uint32_t value, uint32_t *high)
{
    uint32_t low_product = factor * (value & 0xffffu);
    uint32_t high_product = factor * (value >> 16);
    uint32_t low = low_product + (high_product << 16);
    *high = (high_product >> 16) + (low < low_product);
    return low;
}

static uint32_t divide_48_by_32_round(uint32_t high, uint32_t low, uint32_t divisor)
{
    uint32_t quotient = 0;
    uint32_t remainder = 0;
    for (uint32_t bit = 48; bit-- > 0;) {
        uint32_t input_bit = bit >= 32 ? (high >> (bit - 32)) & 1u : (low >> bit) & 1u;
        uint32_t threshold = (divisor >> 1) + ((divisor & 1u) & (input_bit ^ 1u));
        uint32_t next = (remainder << 1) + input_bit;
        if (remainder >= threshold) {
            next -= divisor;
            if (bit < 32)
                quotient |= 1u << bit;
        }
        remainder = next;
    }
    return quotient + (remainder >= (divisor >> 1) + (divisor & 1u));
}

static uint32_t render_channel(uint32_t base, uint32_t zone_gain, uint32_t global_gain)
{
    uint32_t gains = zone_gain * global_gain;
    uint32_t high;
    uint32_t low = multiply_16_by_32(base, gains, &high);
    return divide_48_by_32_round(high, low, GAIN_SCALE);
}

static uint32_t envelope_gain(uint32_t start_time, uint32_t start_gain, uint32_t end_time, uint32_t end_gain, uint32_t time, uint32_t interpolation)
{
    if (time == end_time)
        return end_gain;
    if (time == start_time || interpolation == 0)
        return start_gain;
    uint32_t magnitude;
    uint32_t subtract;
    if (end_gain >= start_gain) {
        magnitude = end_gain - start_gain;
        subtract = 0;
    } else {
        magnitude = start_gain - end_gain;
        subtract = 1;
    }
    uint32_t high;
    uint32_t low = multiply_16_by_32(magnitude, time - start_time, &high);
    uint32_t adjustment = divide_48_by_32_round(high, low, end_time - start_time);
    return subtract ? start_gain - adjustment : start_gain + adjustment;
}

static uint32_t envelope_entry(uint8_t *output, uint32_t validate)
{
    uint32_t time = custom_state.index * 34;
    uint32_t duration = custom_state.initial * 34;
    uint32_t key_offset = 0;
    uint32_t zone_mask = 0;
    if (!validate) {
        for (uint32_t zone = 0; zone < 45; zone++)
            output[zone] = 0;
    }
    for (uint32_t track = 0; track < custom_state.frame_count; track++) {
        uint8_t table[6];
        uint32_t table_address = payload_address() + CUSTOM_HEADER_SIZE + custom_state.palette_bytes + track * 6;
        if (eeprom_read(table_address, table, 6) != 0)
            return 0;
        uint32_t zone = table[0];
        uint32_t color_index = table[1];
        uint32_t interpolation = table[2];
        uint32_t count = table[3];
        uint32_t first = load16(table + 4);
        if (zone >= 15 || (zone_mask & (1u << zone)) || color_index >= custom_state.palette_count ||
            interpolation > 1 || !count || first != key_offset || key_offset > custom_state.timeline_count ||
            count > custom_state.timeline_count - key_offset)
            return 0;
        zone_mask |= 1u << zone;
        uint8_t current[6] __attribute__((aligned(4)));
        uint8_t next[6] __attribute__((aligned(4)));
        if (eeprom_read(timeline_address() + key_offset * 6, current, 6) != 0)
            return 0;
        uint32_t previous_time = 0;
        uint32_t found = 0;
        for (uint32_t key = 0; key < count; key++) {
            uint32_t start_time = load32(current);
            uint32_t start_gain = load16(current + 4);
            if (start_time > duration || (key == 0 ? start_time != 0 : start_time <= previous_time))
                return 0;
            uint32_t end_time = start_time;
            uint32_t end_gain = start_gain;
            if (key + 1 < count) {
                if (eeprom_read(timeline_address() + (key_offset + key + 1) * 6, next, 6) != 0)
                    return 0;
                end_time = load32(next);
                end_gain = load16(next + 4);
                if (end_time <= start_time || end_time > duration)
                    return 0;
            } else if (start_time != duration) {
                return 0;
            }
            if (!validate && !found && start_time <= time && time <= end_time) {
                uint32_t gain = envelope_gain(start_time, start_gain, end_time, end_gain, time, interpolation);
                uint8_t color[3];
                if (!palette_color(color_index, color))
                    return 0;
                for (uint32_t channel = 0; channel < 3; channel++)
                    output[zone * 3 + channel] = render_channel(color[channel], gain, custom_state.global_gain);
                found = 1;
            }
            previous_time = start_time;
            if (key + 1 < count)
                copy_bytes(current, next, 6);
        }
        if (!validate && !found)
            return 0;
        key_offset += count;
    }
    return key_offset == custom_state.timeline_count;
}

static uint32_t decode_entry(uint8_t *output, uint32_t validate)
{
    if (custom_state.codec == 3) {
        if (custom_state.index >= custom_state.initial || !envelope_entry(output, validate))
            return 0;
        custom_state.index++;
        return 1;
    }
    if (custom_state.index >= custom_state.timeline_count)
        return 0;
    uint32_t result = custom_state.codec == 1 ? dictionary_entry(output) : delta_entry(output);
    if (!result)
        return 0;
    custom_state.index++;
    return 1;
}

static void reset_playback(void)
{
    custom_state.index = 0;
    custom_state.delta_offset = 0;
    custom_state.remaining = 0;
}

static uint32_t validate_animation(void)
{
    reset_playback();
    if (custom_state.codec == 3)
        return envelope_entry(custom_scratch, 1);
    if (custom_state.codec == 1) {
        uint32_t width = custom_state.palette_count ? (custom_state.palette_count <= 16 ? 4 : 8) : 0;
        uint32_t stride = width == 0 ? 45 : (width == 4 ? 8 : 15);
        for (uint32_t frame = 0; frame < custom_state.frame_count; frame++) {
            uint32_t address = payload_address() + CUSTOM_HEADER_SIZE + custom_state.palette_bytes + frame * stride;
            if (!(width == 0 ? raw_frame(address, custom_scratch) : packed_frame(address, width, custom_scratch)))
                return 0;
        }
    }
    for (uint32_t index = 0; index < custom_state.timeline_count; index++) {
        if (!decode_entry(custom_scratch, 1))
            return 0;
    }
    return custom_state.codec != 2 || custom_state.delta_offset == custom_state.timeline_bytes;
}

static uint32_t boot_bank(uint32_t bank, uint32_t generation)
{
    custom_state.bank = bank;
    custom_state.generation = generation;
    custom_state.state = CUSTOM_STATE_EMPTY;
    if (!decode_header_at(bank + CUSTOM_BANK_HEADER) || !validate_animation())
        return 0;
    custom_state.state = CUSTOM_STATE_VALID;
    reset_playback();
    set_direct_mode();
    runtime_owner_ram = OWNER_CUSTOM;
    return 1;
}

uint32_t custom_boot(void)
{
    custom_state.decoding = 0;
    custom_state.total_size = 0;
    custom_state.codec = 0;
    custom_state.index = 0;
    custom_state.delta_offset = 0;
    custom_state.remaining = 0;
    runtime_owner_ram = 0;
    custom_state.state = CUSTOM_STATE_EMPTY;
    custom_state.generation = 0;
    uint32_t generation_a = 0;
    uint32_t generation_b = 0;
    uint32_t valid_a = bank_valid(CUSTOM_BANK_A, &generation_a);
    uint32_t valid_b = bank_valid(CUSTOM_BANK_B, &generation_b);
    if (valid_b && (!valid_a || generation_b > generation_a)) {
        if (boot_bank(CUSTOM_BANK_B, generation_b))
            return 1;
        valid_b = 0;
    }
    if (valid_a && boot_bank(CUSTOM_BANK_A, generation_a))
        return 1;
    if (valid_b && boot_bank(CUSTOM_BANK_B, generation_b))
        return 1;
    return 0;
}

void custom_tick(void)
{
    custom_state.decoding = 1;
    if (runtime_owner_ram != OWNER_CUSTOM || custom_state.state != CUSTOM_STATE_VALID)
        goto done;
    if (custom_state.remaining) {
        custom_state.remaining--;
        goto done;
    }
    uint32_t end = custom_state.codec == 3 ? custom_state.initial : custom_state.timeline_count;
    if (custom_state.index >= end) {
        if (custom_state.flags & CUSTOM_LOOP) {
            reset_playback();
        } else {
            if (custom_state.flags & CUSTOM_END_OFF) {
                for (uint32_t index = 0; index < 45; index++)
                    CUSTOM_RGB[index] = 0;
            }
            goto done;
        }
    }
    if (!decode_entry((uint8_t *)CUSTOM_RGB, 0) || (custom_state.codec != 3 && !custom_state.remaining)) {
        custom_state.state = CUSTOM_STATE_EMPTY;
        runtime_owner_ram = 0;
        goto done;
    }
    if (custom_state.codec != 3)
        custom_state.remaining--;
done:
    custom_state.decoding = 0;
}

void custom_get_capabilities(uint8_t *packet)
{
    for (uint32_t index = 4; index < 64; index++)
        packet[index] = 0;
    packet[4] = 1;
    packet[5] = custom_state.state;
    packet[6] = 0x1f;
    packet[7] = custom_state.codec;
    packet[8] = custom_state.state == CUSTOM_STATE_VALID;
    store16(packet + 9, CUSTOM_PAYLOAD_MAX);
    store16(packet + 11, custom_state.total_size);
    store32(packet + 13, custom_state.generation);
    store32(packet + 17, custom_state.upload_offset);
    store32(packet + 21, custom_state.last_status);
    store16(packet + 25, 34);
    store16(packet + 27, 256);
    store16(packet + 29, 15);
    store32(packet + 31, 65535);
}

static void make_bank_header(uint8_t *header, uint32_t state, uint32_t generation, uint32_t total_size)
{
    for (uint32_t index = 0; index < CUSTOM_BANK_HEADER; index++)
        header[index] = 0;
    store32(header, CUSTOM_MAGIC);
    store16(header + 4, 1);
    store16(header + 6, state);
    store32(header + 8, generation);
    store16(header + 12, total_size);
    store32(header + 60, crc32_bytes(header, 60));
}

static uint32_t initialize_upload_bank(uint32_t bank, uint32_t state, uint32_t generation, uint32_t total_size)
{
    uint8_t header[CUSTOM_BANK_HEADER] __attribute__((aligned(4)));
    make_bank_header(header, state, generation, total_size);
    return eeprom_write(bank, header, CUSTOM_BANK_HEADER) == 0;
}

uint32_t custom_upload_begin(uint8_t *packet)
{
    uint32_t total_size = load16(packet + 3);
    uint32_t bank = custom_state.bank == CUSTOM_BANK_A ? CUSTOM_BANK_B : CUSTOM_BANK_A;
    if (total_size == 0 || total_size > CUSTOM_PAYLOAD_MAX || packet[5] < 1 || packet[5] > 3 || custom_state.decoding) {
        custom_state.last_status = 1;
        return 1;
    }
    runtime_owner_ram = 0;
    custom_state.state = CUSTOM_STATE_UPLOADING;
    custom_state.upload_offset = 0;
    custom_state.total_size = total_size;
    custom_state.codec = packet[5];
    custom_state.last_status = 0;
    custom_state.generation++;
    custom_state.bank = bank;
    reset_playback();
    if (!initialize_upload_bank(bank, CUSTOM_STATE_UPLOADING, custom_state.generation, total_size)) {
        custom_state.state = CUSTOM_STATE_EMPTY;
        custom_state.last_status = 3;
        return 3;
    }
    return 0;
}

uint32_t custom_upload_data(uint8_t *packet, uint32_t length)
{
    uint32_t offset = load16(packet + 3);
    if (length < 5 || custom_state.decoding) {
        custom_state.last_status = 2;
        return 2;
    }
    uint32_t count = custom_state.total_size - offset;
    if (count > 48)
        count = 48;
    if (custom_state.state != CUSTOM_STATE_UPLOADING || offset != custom_state.upload_offset ||
        count == 0 || offset + count > custom_state.total_size) {
        custom_state.last_status = 2;
        return 2;
    }
    if (eeprom_write(custom_state.bank + CUSTOM_BANK_HEADER + offset, packet + 5, count) != 0) {
        custom_state.last_status = 3;
        return 3;
    }
    custom_state.upload_offset += count;
    custom_state.last_status = 0;
    return 0;
}

uint32_t custom_upload_commit(void)
{
    if (custom_state.state != CUSTOM_STATE_UPLOADING || custom_state.upload_offset != custom_state.total_size ||
        custom_state.decoding) {
        custom_state.last_status = 4;
        return 4;
    }
    runtime_owner_ram = 0;
    if (!decode_header_at(custom_state.bank + CUSTOM_BANK_HEADER) || !validate_animation()) {
        custom_state.last_status = 5;
        return 5;
    }
    uint32_t computed;
    uint8_t expected_bytes[4];
    if (!crc32_eeprom(custom_state.bank + CUSTOM_BANK_HEADER, custom_state.total_size, &computed) ||
        eeprom_read(custom_state.bank + CUSTOM_BANK_HEADER + 28, expected_bytes, 4) != 0) {
        custom_state.last_status = 6;
        return 6;
    }
    if (computed != load32(expected_bytes)) {
        custom_state.last_status = 6;
        return 6;
    }
    uint8_t expected[CUSTOM_BANK_HEADER] __attribute__((aligned(4)));
    uint8_t actual[CUSTOM_BANK_HEADER] __attribute__((aligned(4)));
    make_bank_header(expected, CUSTOM_STATE_VALID, custom_state.generation, custom_state.total_size);
    if (eeprom_write(custom_state.bank, expected, CUSTOM_BANK_HEADER) != 0 || !read_bank_header(custom_state.bank, actual)) {
        custom_state.last_status = 7;
        return 7;
    }
    for (uint32_t index = 0; index < CUSTOM_BANK_HEADER; index++) {
        if (actual[index] != expected[index]) {
            custom_state.last_status = 7;
            return 7;
        }
    }
    custom_state.state = CUSTOM_STATE_VALID;
    custom_state.last_status = 0;
    reset_playback();
    set_direct_mode();
    runtime_owner_ram = OWNER_CUSTOM;
    return 0;
}

uint32_t custom_upload_abort(void)
{
    if (custom_state.state != CUSTOM_STATE_UPLOADING || custom_state.decoding) {
        custom_state.last_status = 1;
        return 1;
    }
    runtime_owner_ram = 0;
    custom_state.state = CUSTOM_STATE_EMPTY;
    custom_state.upload_offset = 0;
    custom_state.last_status = 0;
    return 0;
}
