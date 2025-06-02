/* 最小限で fib_trie.c が欲しがるマクロ / 型だけ */

// #pragma once
// #include <string.h>
// #include <stdio.h>
// #include <stdbool.h>
// #include <linux/types.h>  
// #include <linux/list.h>
// #include <linux/printk.h>


// /*------ RCU 系を “ただの代入” にする ---------------*/
// #define rcu_assign_pointer(p,v)   ((p) = (v))
// #define rcu_dereference(p)        (p)
// #define rcu_dereference_raw(p)    (p)
// #define call_rcu(h,f)             (f)((struct rcu_head*)(h))
// struct rcu_head { void *next; };

// /*------ メモリ確保を libc に置換 -------------------*/
// #ifndef GFP_KERNEL
// #define GFP_KERNEL   0
// #endif

// #ifndef GFP_ATOMIC
// #define GFP_ATOMIC   0
// #endif

// #ifndef __KERNEL__
// #include <stddef.h>
// #define kzalloc(sz, gfp)          calloc(1, (sz))
// #define kmalloc(sz, gfp)          malloc(sz)
// #define kfree(p)                  free(p)
// #define kfree_rcu(p, f)           free(p)
// #endif

// /*------ hlist / list マクロの最小化 ----------------*/

// /*------ デバッグプリント ---------------------------*/
// #define pr_debug(fmt, ...)  \
//         fprintf(stderr, "trie: " fmt, ##__VA_ARGS__)
//         /* lctrie_user.h  — 既存内容の先頭あたりに追記 --------------------------- */
#ifndef LCTRIE_USER_H
#define LCTRIE_USER_H
#pragma once

#include <stdint.h>          /* ← これを追加 */
#include <netinet/in.h>      /* htonl / ntohl 用 */
#include <linux/types.h>
#include <asm/byteorder.h>  
#include <linux/ip.h>
#include <linux/in_route.h>
#define CONFIG_TRACEPOINTS 0          /* tracepoint を全部無効化 */
#define TRACE_EVENT(name, proto, ...)         /* 何もしない */
#define TRACE_EVENT_FN(name, proto, ...)      /* 何もしない *
/* --- 基本型 --------------------------------------------------------- */
typedef uint32_t u32;
typedef uint8_t  u8;
typedef uint32_t t_key;

/* --- ユーザー空間向けダミー構造体／定数 ------------------------------ */
struct fib_table;
struct netlink_ext_ack { int dummy; };

#define RTN_UNICAST      1
#define RTPROT_STATIC    4
#define RT_SCOPE_UNIVERSE 0

// struct fib_config {
//         uint32_t fc_dst;
//         uint8_t  fc_dst_len;
//         uint8_t  fc_type;
//         uint8_t  fc_protocol;
//         uint8_t  fc_scope;
//         uint32_t fc_table;
// };
struct fib_config {
	u8			fc_dst_len;
	// dscp_t			fc_dscp;
	u8			fc_protocol;
	u8			fc_scope;
	u8			fc_type;
	u8			fc_gw_family;
	/* 2 bytes unused */
	u32			fc_table;
	__be32			fc_dst;
	union {
		__be32		fc_gw4;
		struct in6_addr	fc_gw6;
	};
	int			fc_oif;
	u32			fc_flags;
	u32			fc_priority;
	__be32			fc_prefsrc;
	u32			fc_nh_id;
	struct nlattr		*fc_mx;
	struct rtnexthop	*fc_mp;
	int			fc_mx_len;
	int			fc_mp_len;
	u32			fc_flow;
	u32			fc_nlflags;
	// struct nl_info		fc_nlinfo;
	struct nlattr		*fc_encap;
	// u16			fc_encap_type;
};

/* ルックアップ用の簡易構造体（本家 flowi4 の必要分だけ） */
struct flowi4 { uint32_t daddr; 
   uint32_t saddr; 
};

/* 結果バッファ（中身は使わないなら空で OK） */
struct fib_result {
	__be32			prefix;
	unsigned char		prefixlen;
	unsigned char		nh_sel;
	unsigned char		type;
	unsigned char		scope;
	u32			tclassid;
	struct fib_nh_common	*nhc;
	struct fib_info		*fi;
	struct fib_table	*table;
	struct hlist_head	*fa_head;
};


/* --- fib_trie.c が提供する関数プロトタイプ --------------------------- */
struct fib_table *fib_trie_table(u32 id, void *net);
void              fib_trie_free (struct fib_table *tb);
int  fib_table_insert (void *net, struct fib_table *tb,
                       struct fib_config *cfg,
                       struct netlink_ext_ack *extack);
int  fib_table_lookup (struct fib_table *tb, struct flowi4 *flp,
                       struct fib_result *res, int fib_flags);

struct trie {
struct key_vector *kv;
#ifdef CONFIG_IP_FIB_TRIE_STATS
void *stats;
#endif
};

struct key_vector {
    t_key    key;    /* プレフィックスそのもの (ビッグエンディアンではなくて ntohl 後の形式) */
    uint8_t  pos;    /* bit 単位の深さ。ルートでは 32  */
    uint8_t  bits;   /* このノードで保持しているビット長（ルートなら 0） */
    uint8_t  slen;   /* このノード以下に残っているビット長 (ルートなら 32) */
    union {
        struct {
            struct fib_alias *first;   /* 葉ノード時に実際のルーティング情報を指す */
        } leaf;
        /* 中間ノードで使われる tnode ポインタ。wrapper.c では直接触らないので不透明。 */
        struct tnode *__empty_tnode;
        struct tnode *tnode;
    } u;
};

/* fib_alias は同じくカーネル内で使う構造体だが、
 * lctrie_insert()/lookup() では中身を参照しないので前方宣言だけしておく */
struct fib_alias;

/* 中間ノード（tnode）についてもカーネル内実装では別構造体だが、
 * wrapper.c では要素サイズ（sizeof(struct tnode)）しか使わないので
 * ここでは不透明型としておく */
struct tnode;
struct fib_table {
    /* hlist_node, tb_id, tb_num_default, rcu はここでは使わない */
    /* 最低限 ”tb_data が何らかのアドレスを指している” というレイアウトだけ再定義する */
    unsigned long *tb_data;
    // struct hlist_node	tb_hlist;
	u32			tb_id;
	int			tb_num_default;
	unsigned long		__data[];
    /* __data[] は可変長で、コンパイル時には不要 */
};

/* --------------------------------------------------------------------------
   ----------
   以下はもともとの lctrie_user.h の中身（wrapper.c 側 API）を続ける
   ----------
---------------------------------------------------------------------------- */

/* ───── ユーザ向け API ────────────────────────────────────────── */

/* lctrie 構造体そのもの */
struct lctrie {
    struct fib_table *table;
};

struct lctrie *lctrie_new(void);
void           lctrie_insert(struct lctrie *t, uint32_t prefix, uint8_t plen);
int            lctrie_lookup(struct lctrie *t, uint32_t addr);
void          lctrie_free(struct lctrie *t);
void fib_trie_init(void);  /* 初期化関数。必要なら呼ぶ */

#endif  /* LCTRIE_USER_H */
