.syntax unified
.thumb
.cpu cortex-m0

.global dispatch_set_hook
.type dispatch_set_hook, %function
dispatch_set_hook:
    cmp r0, #0x25
    beq .Lset_effect
    cmp r0, #0x23
    beq .Lsave_current
    cmp r0, #0x04
    beq .Lmaybe_set_mode
    cmp r0, #0x13
    bgt .Lset_return
    blt .Lset_subtract
    ldr r0, =0x3105
    bx r0
.Lmaybe_set_mode:
    ldrb r0, [r4, #2]
    cmp r0, #1
    beq .Lset_mode
    cmp r0, #2
    bne .Lrestore_set_field
.Lset_mode:
    movs r5, #0
    mov r0, r4
    bl set_stock_mode
    ldr r0, =0x32fb
    bx r0
.Lrestore_set_field:
    movs r0, #0x04
.Lset_subtract:
    subs r0, #2
    ldr r1, =0x30d3
    bx r1
.Lset_return:
    bx lr
.Lsave_current:
    movs r5, #0
    bl save_current
    ldr r0, =0x32fb
    bx r0
.Lset_effect:
    movs r5, #0
    mov r0, r4
    bl set_effect_recipe
    ldr r0, =0x32fb
    bx r0

.global dispatch_get_hook
.type dispatch_get_hook, %function
dispatch_get_hook:
    cmp r0, #0x60
    beq .Lget_iap_debug
    cmp r0, #0x25
    beq .Lget_profile
    cmp r0, #0x24
    beq .Lget_eeprom
    cmp r0, #0x23
    beq .Lget_saved
    cmp r0, #0x22
    bne .Lget_return
    movs r5, #49
    mov r0, r4
    bl get_current_response
    ldr r0, =0x32fb
    bx r0
.Lget_return:
    bx lr
.Lget_saved:
    movs r5, #50
    mov r0, r4
    bl get_saved_response
    ldr r0, =0x32fb
    bx r0
.Lget_profile:
    movs r5, #64
    mov r0, r4
    bl get_profile_response
    ldr r0, =0x32fb
    bx r0
.Lget_eeprom:
    movs r5, #61
    mov r0, r4
    bl get_eeprom_dump_response
    ldr r0, =0x32fb
    bx r0
.Lget_iap_debug:
    movs r5, #64
    mov r0, r4
    bl get_iap_debug_response
    ldr r0, =0x32fb
    bx r0
