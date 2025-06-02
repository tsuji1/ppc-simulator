/* ----- stubs_mem.c  : 必要なメモリ系 API をラップ ------------------- */
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdio.h>
/* ---------- kmalloc / kfree ------------------------------------------ */
void *kmalloc_noprof(size_t sz, unsigned int gfp)          { return malloc(sz); }
/* ── fib_alias の大きさだけ確保して返す ── */
extern void *trie_leaf_kmem;  // kmem_cache_create("trie_leaf", sizeof(struct key_vector), ...);
extern void *fn_alias_kmem;   // kmem_cache_create("fib_alias", sizeof(struct fib_alias), ...);

void *kmem_cache_alloc_noprof(void *cache, unsigned gfp)
{
    (void)gfp;  // GFP_KERNEL フラグは無視 OK
    
    return  malloc((size_t)cache);  // cache はサイズを表す値として使われる
}

void  kmem_cache_free(void *cache, void *p)                { free(p); }
void *vzalloc_noprof(size_t sz)                            { return calloc(1, sz); }
void  kvfree(const void *p)                                { free((void *)p); }
void  kfree(const void *p)                                 { free((void *)p); }
void *kvfree_call_rcu(const void *p, void *rcu)            { free((void *)p); return NULL; }

/* ---------- slab cache “create”/“size” ダミー ------------------------ */
void *__kmem_cache_create_args(const char *n, size_t sz, size_t a,
                               unsigned long f, void *ctor)
{
        /* 呼び出し側は戻り値をキャッシュハンドル扱い → サイズを覚えさせる   */
        return (void *)sz;
}

/* ---------- その他メモリ/文字列 ------------------------------------- */
void *vzalloc(size_t sz)                                   { return calloc(1, sz); }
int   snprintf(char *buf, size_t n, const char *fmt, ...)  { return 0; } /* 最小 */
/* -------------------------------------------------------------------- */

/* ----- stubs_misc.c : それ以外は全部 no-op で埋める ------------------ */
#include <stdint.h>
#include "include/lctrie_user.h"

#define STUB0(name, ret)        ret name(void)                 { return (ret)0; }
#define STUB1(name, ret, a)     ret name(a x)                  { return (ret)0; }
#define STUB2(name, ret, a,b)   ret name(a x,b y)              { return (ret)0; }

STUB0(call_rcu,               void)
STUB0(synchronize_net,        void)
STUB0(__rcu_read_lock,        void)
STUB0(__rcu_read_unlock,      void)
STUB0(refcount_warn_saturate, void)
STUB0(remove_proc_entry,      void)
STUB0(proc_create_net_data,   void *)
STUB0(proc_create_net_single, void *)
STUB0(rt_cache_flush,         void)
STUB0(rtnl_notify,            void)
STUB0(rtnl_set_sk_err,        void)
STUB0(sk_skb_reason_drop,     void)
STUB0(seq_printf,             int)
STUB0(seq_write,              int)
STUB0(seq_putc,               int)
STUB0(seq_pad,                int)

/* --------- ルーティング関係 (全部失敗/空) --------------------------- */
STUB1(fib_get_table,          struct fib_table *, uint32_t)
// STUB0(fib_alias_hw_flags_set, void)
STUB0(fib_nlmsg_size,         int)
STUB0(fib_info_nh_uses_dev,   int)
STUB0(fib_metrics_match,      int)
STUB0(fib_nh_match,           int)
STUB0(rtmsg_fib,              void)
STUB0(call_fib4_notifier,     int)
STUB0(call_fib4_notifiers,    int)
STUB0(cpu_number,             int)
STUB0(__cpu_online_mask,      int)
STUB0(__preempt_count,        int)
STUB0(__SCK__tp_func_fib_table_lookup, int)
STUB0(__SCK__preempt_schedule_notrace,int)
STUB0(__SCT__tp_func_fib_table_lookup,int)
STUB0(__SCT__preempt_schedule_notrace,int)
STUB0(__tracepoint_fib_table_lookup,  int)

/* fib_trie が export しているが quick_test で呼ぶのは解放だけ */
void fib_trie_free(struct fib_table *t) {}

/* -------------------------------------------------------------------- */
struct sk_buff { char _dummy; };           /* 最小ダミー構造体           */
typedef unsigned int gfp_t;
struct netlink_callback { int _d; };

/* ---- 未解決 6 個を正しいプロトタイプで ---- */
struct sk_buff *
__alloc_skb(unsigned int size, gfp_t gfp, int flags, int node) 
{ return malloc(size); }

int fib_create_info(struct fib_config *cfg,
                    struct netlink_ext_ack *ext) 
{ return 0; }

void fib_release_info(void *fi)  {}

int fib_dump_info(struct sk_buff *skb, struct netlink_callback *cb, int family,
                  struct fib_table *tb, struct fib_result *res,
                  int idx, int type) 
{ return 0; }

int fib_dump_info_fnhe(struct sk_buff *skb, struct netlink_callback *cb,
                       int family, struct fib_table *tb,
                       struct fib_result *res, int idx, int type) 
{ return 0; }

unsigned int fib_props(void *res)  { return 0; }


void *__kmalloc_noprof(size_t sz, unsigned int gfp)
{
    (void)gfp;                           /* フラグは無視 */
    return calloc(1, sz);                /* 0 クリアした領域を返す */
}


/* kvzalloc はしばしば alias なので念のため */
void *kvzalloc(size_t sz, unsigned int gfp)
{
    (void)gfp;
    return calloc(1, sz);
}
