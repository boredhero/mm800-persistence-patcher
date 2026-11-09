#ifndef CUSTOM_ANIMATION_H
#define CUSTOM_ANIMATION_H

#include <stdint.h>

#define OWNER_CUSTOM 5u
#define CUSTOM_BANK_A 0x180u
#define CUSTOM_BANK_B 0x880u
#define CUSTOM_BANK_HEADER 64u
#define CUSTOM_PAYLOAD_MAX 1728u

uint32_t custom_boot(void);
void custom_tick(void);
void custom_get_capabilities(uint8_t *packet);
uint32_t custom_upload_begin(uint8_t *packet);
uint32_t custom_upload_data(uint8_t *packet, uint32_t length);
uint32_t custom_upload_commit(void);
uint32_t custom_upload_abort(void);

#endif
