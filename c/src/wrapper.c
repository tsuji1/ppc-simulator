/* wrapper.c
 *
 *  - fib_trie.c を **改変せず** 取り込む
 *  - カーネル依存の関数／マクロだけ最小限スタブ化
 *  - 外部に公開するのは lctrie_* API
 */

 #include "lctrie_user.h"      /* スタブ群 (次のブロックを参照) */


 /* ───── fib_trie.c をインクルード（オリジナル構造体は保持） ──── */
 
// #include "fib_trie.c"  /* fib_trie_table, fib_table_insert, fib_table_lookup など */
#include <arpa/inet.h> 
#include <stdlib.h>      /* calloc, free, NULL */
#include <stddef.h>      /* NULL (stdlib.h でも可) */

#define KEYLENGTH 32
#include <linux/netlink.h> 
 /* ───── ユーザ向け API ────────────────────────────────────────── */
 
/* --------------------------------------------------------------------------
   lctrie_new
   ・fib_trie_table() でテーブル本体（struct fib_table + 可変長データ）を確保
   ・その後、tb_data の先にある struct trie を手動で初期化しておく
---------------------------------------------------------------------------- */
struct lctrie *lctrie_new(void)
{
    fib_trie_init();
    struct lctrie *h = calloc(1, sizeof(*h));
    if (!h)
        return NULL;
    

    
    /* (1) カーネル相当の fib_trie_table() 呼び出し */
    h->table = fib_trie_table(1234, NULL);
    if (!h->table) {
        free(h);
        return NULL;
    }
    /* ↓ ここで t が NULL だったら、自前で簡易的に tb_data 領域を確保  */
    // if (!h->table->tb_data) {
    //     struct trie *fake = malloc(sizeof(struct trie));
    //     if (!fake) { 
    //         fib_trie_free(h->table);
    //         free(h);
    //         return NULL;
    //     }
    //     memset(fake, 0, sizeof(*fake));
    //     /* fake->kv だけは後で lctrie_insert が使うので malloc しておく */
    //     fake->kv = malloc(sizeof(*(fake->kv)));
    //     memset(fake->kv, 0, sizeof(*(fake->kv)));
    //     h->table->tb_data = (unsigned long *)fake;
    // }

    /* (2) tb_data の先にある struct trie を取得 */
    {
        struct trie *t = (struct trie *)h->table->tb_data;
        if (!t) {
            /* あってはいけないが念のため */
            fib_trie_free(h->table);
            free(h);
            return NULL;
        }

        /*
         * (3) ルートノード用の key_vector を確保・初期化しておく
         *    └ t->kv が NULL だと以降の検索/挿入で参照できずセグフォルトになるので
         */
        t->kv = malloc(sizeof(*(t->kv)));
        if (!t->kv) {
            fib_trie_free(h->table);
            free(h);
            return NULL;
        }
        memset(t->kv, 0, sizeof(*(t->kv)));

        /* ルートノードの最小初期化:
         *  - key=0
         *  - bits=0
         *  - pos = KEYLENGTH
         *  - slen = KEYLENGTH
         *  - leaf.first = NULL
         */
        t->kv->key           = 0;
        t->kv->bits          = 0;
        t->kv->pos           = KEYLENGTH;
        t->kv->slen          = KEYLENGTH;
        t->kv->u.leaf.first  = NULL;

        /* （もし t->stats があればゼロクリアするなど、本家の初期化をまねる） */
#ifdef CONFIG_IP_FIB_TRIE_STATS
        t->stats = NULL;
#endif
    }

    return h;
}

/* --------------------------------------------------------------------------
   lctrie_insert
   ・prefix/plen を fib_config に乗せて fib_table_insert() を呼ぶ
---------------------------------------------------------------------------- */
void lctrie_insert(struct lctrie *h, uint32_t prefix, uint8_t plen)
{
    if (!h || !h->table)
        return;

    struct fib_config cfg;
    memset(&cfg, 0, sizeof(cfg));

    /* 必須フィールドを埋める */
    cfg.fc_dst      = htonl(prefix);
    cfg.fc_dst_len  = plen;
    cfg.fc_type     = RTN_UNICAST;
    cfg.fc_protocol = RTPROT_STATIC;
    cfg.fc_scope    = RT_SCOPE_UNIVERSE;
    cfg.fc_table    = 1234;
    cfg.fc_nlflags  = NLM_F_CREATE;  /* 新規作成フラグを必ず立てる */

    struct netlink_ext_ack ext;
    memset(&ext, 0, sizeof(ext));

    printf("DEBUG: lctrie_insert called with prefix = 0x%08x, plen = %u\n",
           prefix, plen);

    fib_table_insert(NULL, h->table, &cfg, &ext);
}

/* --------------------------------------------------------------------------
   lctrie_lookup
   ・addr の単純ルックアップ。見つかれば 1 を返す。エラー／未ヒットは 0。
---------------------------------------------------------------------------- */
int lctrie_lookup(struct lctrie *h, uint32_t addr)
{
    if (!h || !h->table)
        return 0;

    struct flowi4 fl = { .daddr = htonl(addr) };
    struct fib_result res;
    /* addr はホストオーダーで 0x0A000005 (167772165) のはず */
    printf("DEBUG: called with addr (host‐order) = 0x%08x (%u)\n",
        addr, addr);
    
    /* fl.daddr はネットワークオーダーになっているので、ntohl して戻す */
    printf("DEBUG: fl.daddr (network‐order)   = 0x%08x (%u)\n",
           fl.daddr, fl.daddr);
    printf("DEBUG: fl.daddr (as host‐order)   = 0x%08x (%u)\n",
           ntohl(fl.daddr), ntohl(fl.daddr));

    /* fib_table_lookup() が 0 を返せば “見つかった” とみなす */
    return (fib_table_lookup(h->table, &fl, &res, 0) == 0) ? 1 : 0;
}

/* --------------------------------------------------------------------------
   lctrie_free
   ・内部で fib_trie_free() を呼んで構造体全体を解放
   ・さらに、(ここで malloc した t->kv も必要なら free する)
---------------------------------------------------------------------------- */
void lctrie_free(struct lctrie *h)
{
    if (!h)
        return;

    if (h->table) {
        struct trie *t = (struct trie *)h->table->tb_data;
        if (t) {
            /* もし t->kv を自前で malloc していれば free しておく */
            if (t->kv) {
                free(t->kv);
                t->kv = NULL;
            }
        }
        fib_trie_free(h->table);
    }
    free(h);
}
