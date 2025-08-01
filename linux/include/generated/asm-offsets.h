#ifndef __ASM_OFFSETS_H__
#define __ASM_OFFSETS_H__
/*
 * DO NOT MODIFY.
 *
 * This file was generated by Kbuild
 */


#define KVM_STEAL_TIME_preempted 16 /* offsetof(struct kvm_steal_time, preempted) */

#define pt_regs_bx 40 /* offsetof(struct pt_regs, bx) */
#define pt_regs_cx 88 /* offsetof(struct pt_regs, cx) */
#define pt_regs_dx 96 /* offsetof(struct pt_regs, dx) */
#define pt_regs_sp 152 /* offsetof(struct pt_regs, sp) */
#define pt_regs_bp 32 /* offsetof(struct pt_regs, bp) */
#define pt_regs_si 104 /* offsetof(struct pt_regs, si) */
#define pt_regs_di 112 /* offsetof(struct pt_regs, di) */
#define pt_regs_r8 72 /* offsetof(struct pt_regs, r8) */
#define pt_regs_r9 64 /* offsetof(struct pt_regs, r9) */
#define pt_regs_r10 56 /* offsetof(struct pt_regs, r10) */
#define pt_regs_r11 48 /* offsetof(struct pt_regs, r11) */
#define pt_regs_r12 24 /* offsetof(struct pt_regs, r12) */
#define pt_regs_r13 16 /* offsetof(struct pt_regs, r13) */
#define pt_regs_r14 8 /* offsetof(struct pt_regs, r14) */
#define pt_regs_r15 0 /* offsetof(struct pt_regs, r15) */
#define pt_regs_flags 144 /* offsetof(struct pt_regs, flags) */

#define saved_context_cr0 200 /* offsetof(struct saved_context, cr0) */
#define saved_context_cr2 208 /* offsetof(struct saved_context, cr2) */
#define saved_context_cr3 216 /* offsetof(struct saved_context, cr3) */
#define saved_context_cr4 224 /* offsetof(struct saved_context, cr4) */
#define saved_context_gdt_desc 266 /* offsetof(struct saved_context, gdt_desc) */

#define CPUINFO_x86 1 /* offsetof(struct cpuinfo_x86, x86) */
#define CPUINFO_x86_vendor 2 /* offsetof(struct cpuinfo_x86, x86_vendor) */
#define CPUINFO_x86_model 0 /* offsetof(struct cpuinfo_x86, x86_model) */
#define CPUINFO_x86_stepping 4 /* offsetof(struct cpuinfo_x86, x86_stepping) */
#define CPUINFO_cpuid_level 40 /* offsetof(struct cpuinfo_x86, cpuid_level) */
#define CPUINFO_x86_capability 48 /* offsetof(struct cpuinfo_x86, x86_capability) */
#define CPUINFO_x86_vendor_id 144 /* offsetof(struct cpuinfo_x86, x86_vendor_id) */

#define TASK_threadsp 2944 /* offsetof(struct task_struct, thread.sp) */
#define TASK_stack_canary 1432 /* offsetof(struct task_struct, stack_canary) */

#define pbe_address 0 /* offsetof(struct pbe, address) */
#define pbe_orig_address 8 /* offsetof(struct pbe, orig_address) */
#define pbe_next 16 /* offsetof(struct pbe, next) */

#define IA32_SIGCONTEXT_ax 44 /* offsetof(struct sigcontext_32, ax) */
#define IA32_SIGCONTEXT_bx 32 /* offsetof(struct sigcontext_32, bx) */
#define IA32_SIGCONTEXT_cx 40 /* offsetof(struct sigcontext_32, cx) */
#define IA32_SIGCONTEXT_dx 36 /* offsetof(struct sigcontext_32, dx) */
#define IA32_SIGCONTEXT_si 20 /* offsetof(struct sigcontext_32, si) */
#define IA32_SIGCONTEXT_di 16 /* offsetof(struct sigcontext_32, di) */
#define IA32_SIGCONTEXT_bp 24 /* offsetof(struct sigcontext_32, bp) */
#define IA32_SIGCONTEXT_sp 28 /* offsetof(struct sigcontext_32, sp) */
#define IA32_SIGCONTEXT_ip 56 /* offsetof(struct sigcontext_32, ip) */

#define IA32_RT_SIGFRAME_sigcontext 164 /* offsetof(struct rt_sigframe_ia32, uc.uc_mcontext) */

#define TDX_MODULE_rcx 0 /* offsetof(struct tdx_module_args, rcx) */
#define TDX_MODULE_rdx 8 /* offsetof(struct tdx_module_args, rdx) */
#define TDX_MODULE_r8 16 /* offsetof(struct tdx_module_args, r8) */
#define TDX_MODULE_r9 24 /* offsetof(struct tdx_module_args, r9) */
#define TDX_MODULE_r10 32 /* offsetof(struct tdx_module_args, r10) */
#define TDX_MODULE_r11 40 /* offsetof(struct tdx_module_args, r11) */
#define TDX_MODULE_r12 48 /* offsetof(struct tdx_module_args, r12) */
#define TDX_MODULE_r13 56 /* offsetof(struct tdx_module_args, r13) */
#define TDX_MODULE_r14 64 /* offsetof(struct tdx_module_args, r14) */
#define TDX_MODULE_r15 72 /* offsetof(struct tdx_module_args, r15) */
#define TDX_MODULE_rbx 80 /* offsetof(struct tdx_module_args, rbx) */
#define TDX_MODULE_rdi 88 /* offsetof(struct tdx_module_args, rdi) */
#define TDX_MODULE_rsi 96 /* offsetof(struct tdx_module_args, rsi) */

#define BP_scratch 484 /* offsetof(struct boot_params, scratch) */
#define BP_secure_boot 492 /* offsetof(struct boot_params, secure_boot) */
#define BP_loadflags 529 /* offsetof(struct boot_params, hdr.loadflags) */
#define BP_hardware_subarch 572 /* offsetof(struct boot_params, hdr.hardware_subarch) */
#define BP_version 518 /* offsetof(struct boot_params, hdr.version) */
#define BP_kernel_alignment 560 /* offsetof(struct boot_params, hdr.kernel_alignment) */
#define BP_init_size 608 /* offsetof(struct boot_params, hdr.init_size) */
#define BP_pref_address 600 /* offsetof(struct boot_params, hdr.pref_address) */

#define PTREGS_SIZE 168 /* sizeof(struct pt_regs) */
#define TLB_STATE_user_pcid_flush_mask 22 /* offsetof(struct tlb_state, user_pcid_flush_mask) */
#define CPU_ENTRY_AREA_entry_stack 4096 /* offsetof(struct cpu_entry_area, entry_stack_page) */
#define SIZEOF_entry_stack 4096 /* sizeof(struct entry_stack) */
#define MASK_entry_stack -4096 /* (~(sizeof(struct entry_stack) - 1)) */
#define TSS_sp0 4 /* offsetof(struct tss_struct, x86_tss.sp0) */
#define TSS_sp1 12 /* offsetof(struct tss_struct, x86_tss.sp1) */
#define TSS_sp2 20 /* offsetof(struct tss_struct, x86_tss.sp2) */

#endif
