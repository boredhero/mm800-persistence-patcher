ENTRY(boot_restore)

SECTIONS
{
    . = 0x4190;
    .text : {
        *(.text.boot_restore)
        *(.text.save_current)
        *(.text.get_saved_response)
        *(.text.dispatch_set_hook)
        *(.text.dispatch_get_hook)
        *(.text*)
        *(.rodata*)
    }
    .patch_state 0x10001900 (NOLOAD) : {
        *(.patch_state)
    }
    /DISCARD/ : {
        *(.comment*)
        *(.note*)
        *(.ARM.attributes)
        *(.ARM.exidx*)
        *(.ARM.extab*)
        *(.eh_frame*)
    }
}
