/*
 * Boot stub for a DIY M0065 on an STM32F103C8T6.
 *
 * ModalAI's M0065 image is linked to run at 0x08001C00 and expects their
 * bootloader to occupy the 7 KB below it. That bootloader is not publicly
 * distributed. It is only needed to update firmware over UART, which is
 * irrelevant when flashing over SWD -- so all that is actually missing is
 * something at the reset vector to hand control to the application.
 *
 * On reset the core loads MSP from 0x08000000 and PC from 0x08000004. This
 * stub lives there, points VTOR at the application vector table, reloads MSP
 * from it, and branches to the application reset handler.
 */

    .syntax unified
    .cpu    cortex-m3
    .thumb

    .equ    APP_BASE,  0x08001C00      /* ModalAI application load address   */
    .equ    SCB_VTOR,  0xE000ED08      /* vector table offset register       */

    .section .isr_vector, "a", %progbits
    .word   _estack                    /* MSP at reset (replaced below)      */
    .word   Reset_Handler

    .text
    .thumb_func
    .global Reset_Handler
    .type   Reset_Handler, %function
Reset_Handler:
    cpsid   i                          /* no interrupts during the handover  */

    ldr     r0, =SCB_VTOR              /* relocate the vector table so the   */
    ldr     r1, =APP_BASE              /* app's handlers are the live ones   */
    str     r1, [r0]
    dsb
    isb

    ldr     r0, [r1]                   /* app word 0: initial stack pointer  */
    msr     msp, r0
    ldr     r0, [r1, #4]               /* app word 1: reset handler          */

    cpsie   i
    bx      r0                         /* never returns                      */

    .size   Reset_Handler, . - Reset_Handler
    .end
