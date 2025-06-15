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


#include <netinet/in.h>      /* htonl / ntohl 用 */
#include <linux/types.h>
#include <asm/byteorder.h>  
#include <linux/ip.h>
#include <linux/in_route.h>
#include <linux/compact_list.h>
#include <linux/compact_rcu.h>
#include <stdbool.h>         /* bool 型のために追加 */
#define CONFIG_TRACEPOINTS 0          /* tracepoint を全部無効化 */
#define TRACE_EVENT(name, proto, ...)         /* 何もしない */
#define TRACE_EVENT_FN(name, proto, ...)      /* 何もしない */
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
#define BITS_PER_LONG 64
#ifndef __rcu
# define __rcu
#endif
/* 以前のマクロ (C 標準のフレキシブル配列) を空定義しておく */
#ifndef DECLARE_FLEX_ARRAY
# define DECLARE_FLEX_ARRAY(type, name) type name[]
#endif

/* ここを “zero-length array” に置き換えるマクロ */
#ifndef _ARRAY
# define _ARRAY(type, name) type name[0]
#endif


// struct fib_config {
//         uint32_t fc_dst;
//         uint8_t  fc_dst_len;
//         uint8_t  fc_type;
//         uint8_t  fc_protocol;
//         uint8_t  fc_scope;
//         uint32_t fc_table;
// };

typedef uint16_t u16;
typedef uint8_t dscp_t;
struct nl_info {
    /* カーネルの nl_info には複数のフィールドがありますが、
     * ユーザ空間で最低限コンパイルを通し、ダミーとして扱うために
     * サイズだけ合わせる例を示します。以下は 8 バイト(+)を仮定*/
    void *dummy1;
    void *dummy2;
};

struct fib_info {
	struct hlist_node	fib_hash;
	struct hlist_node	fib_lhash;
	// struct list_head	nh_list;
	struct net		*fib_net;
	// refcount_t		fib_treeref;
	// refcount_t		fib_clntref;
	unsigned int		fib_flags;
	unsigned char		fib_dead;
	unsigned char		fib_protocol;
	unsigned char		fib_scope;
	unsigned char		fib_type;
	__be32			fib_prefsrc;
	u32			fib_tb_id;
	u32			fib_priority;
	struct dst_metrics	*fib_metrics;
#define fib_mtu fib_metrics->metrics[RTAX_MTU-1]
#define fib_window fib_metrics->metrics[RTAX_WINDOW-1]
#define fib_rtt fib_metrics->metrics[RTAX_RTT-1]
#define fib_advmss fib_metrics->metrics[RTAX_ADVMSS-1]
	int			fib_nhs;
	bool			fib_nh_is_v6;
	bool			nh_updated;
	bool			pfsrc_removed;
	struct nexthop		*nh;
	struct rcu_head		rcu;
	// struct fib_nh		fib_nh[] __counted_by(fib_nhs);
};
typedef struct {
	uid_t val;
} kuid_t;


struct fib_config {
	u8			fc_dst_len;
	dscp_t			fc_dscp;
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
	struct nl_info		fc_nlinfo;
	struct nlattr		*fc_encap;
	u16			fc_encap_type;
};
struct flowi_tunnel {
	__be64			tun_id;
};
struct flowi_common {
	int	flowic_oif;
	int	flowic_iif;
	int     flowic_l3mdev;
	__u32	flowic_mark;
	__u8	flowic_tos;
	__u8	flowic_scope;
	__u8	flowic_proto;
	__u8	flowic_flags;
#define FLOWI_FLAG_ANYSRC		0x01
#define FLOWI_FLAG_KNOWN_NH		0x02
#define FLOWI_FLAG_L3MDEV_OIF		0x04
#define FLOWI_FLAG_ANY_SPORT		0x08
	__u32	flowic_secid;
	kuid_t  flowic_uid;
	__u32		flowic_multipath_hash;
	struct flowi_tunnel flowic_tun_key;
};
union flowi_uli {
	struct {
		__be16	dport;
		__be16	sport;
	} ports;

	struct {
		__u8	type;
		__u8	code;
	} icmpt;

	__be32		gre_key;

	struct {
		__u8	type;
	} mht;
};

struct flowi4 {
	struct flowi_common	__fl_common;
#define flowi4_oif		__fl_common.flowic_oif
#define flowi4_iif		__fl_common.flowic_iif
#define flowi4_l3mdev		__fl_common.flowic_l3mdev
#define flowi4_mark		__fl_common.flowic_mark
#define flowi4_tos		__fl_common.flowic_tos
#define flowi4_scope		__fl_common.flowic_scope
#define flowi4_proto		__fl_common.flowic_proto
#define flowi4_flags		__fl_common.flowic_flags
#define flowi4_secid		__fl_common.flowic_secid
#define flowi4_tun_key		__fl_common.flowic_tun_key
#define flowi4_uid		__fl_common.flowic_uid
#define flowi4_multipath_hash	__fl_common.flowic_multipath_hash

	/* (saddr,daddr) must be grouped, same order as in IP header */
	__be32			saddr;
	__be32			daddr;

	union flowi_uli		uli;
#define fl4_sport		uli.ports.sport
#define fl4_dport		uli.ports.dport
#define fl4_icmp_type		uli.icmpt.type
#define fl4_icmp_code		uli.icmpt.code
#define fl4_mh_type		uli.mht.type
#define fl4_gre_key		uli.gre_key
} __attribute__((__aligned__(BITS_PER_LONG/8)));

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


struct key_vector {
	t_key key;
	unsigned char pos;		/* 2log(KEYLENGTH) bits needed */
	unsigned char bits;		/* 2log(KEYLENGTH) bits needed */
	unsigned char slen;
	union {
		/* This list pointer if valid if (pos | bits) == 0 (LEAF) */
		struct hlist_head leaf;
		/* This array is valid if (pos | bits) > 0 (TNODE) */
		_ARRAY(struct key_vector *, tnode);  /* zero-length array 扱い */
	};
};

struct trie {
struct key_vector kv[1];
#ifdef CONFIG_IP_FIB_TRIE_STATS
void *stats;
#endif
};

/* 中間ノード（tnode）についてもカーネル内実装では別構造体だが、
 * wrapper.c では要素サイズ（sizeof(struct tnode)）しか使わないので
 * ここでは不透明型としておく */
struct tnode {
	struct rcu_head rcu;
	t_key empty_children;		/* KEYLENGTH bits needed */
	t_key full_children;		/* KEYLENGTH bits needed */
	struct key_vector __rcu *parent;
	struct key_vector kv[1];
#define tn_bits kv[0].bits
};

struct fib_table {
	struct hlist_node	tb_hlist;
	u32			tb_id;
	int			tb_num_default;
	struct rcu_head		rcu;
	unsigned long 		*tb_data;
	unsigned long		__data[];
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
void           lctrie_insert(struct lctrie *t, uint32_t prefix, uint8_t plen, uint32_t custom_id);
struct custom_result lctrie_lookup(struct lctrie *t, uint32_t addr);
void          lctrie_free(struct lctrie *t);
void fib_trie_init(void);  /* 初期化関数。必要なら呼ぶ */

typedef  int16_t s16;
struct fib_alias {
	struct hlist_node	fa_list;
	struct fib_info		*fa_info;
	dscp_t			fa_dscp;
	u8			fa_type;
	u8			fa_state;
	u8			fa_slen;
	u32			tb_id;
	s16			fa_default;
	u8			offload;
	u8			trap;
	u8			offload_failed;
	uint32_t           fa_id; 
	struct rcu_head		rcu;
};


#endif  /* LCTRIE_USER_H */
