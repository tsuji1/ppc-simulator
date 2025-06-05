#ifndef _COMPAT_HLIST_H
#define _COMPAT_HLIST_H

#include <stddef.h> /* offsetof を使うため */

/*
 * ユーザ空間で使う hlist (hash list) の最小限定義
 * ほぼ Linux カーネルの <linux/hlist.h> と同等のインターフェースを提供します。
 */

struct hlist_node {
    struct hlist_node *next, **pprev;
};

/* 頭の番兵（バケットの先頭） */
struct hlist_head {
    struct hlist_node *first;
};

/* hlist_head の初期化マクロ */
#define HLIST_HEAD_INIT { .first = NULL }
#define HLIST_HEAD(name) struct hlist_head name = { .first = NULL }

/* hlist_node の初期化マクロ */
#define HLIST_NODE_INIT(n) { .next = NULL, .pprev = NULL }

/* node を初期化してから使う場合 */
static inline void INIT_HLIST_NODE(struct hlist_node *n)
{
    n->next  = NULL;
    n->pprev = NULL;
}

/* head を初期化してから使う場合 */
static inline void INIT_HLIST_HEAD(struct hlist_head *h)
{
    h->first = NULL;
}

/*
 * hlist に node を先頭 (head->first) に挿入する
 *    - node->next に現在の head->first を入れ
 *    - その next ノードの pprev を &node->next にセットし
 *    - head->first を node にセットする
 *    - node->pprev を &head->first にセットする
 */
static inline void hlist_add_head(struct hlist_node *node, struct hlist_head *head)
{
    struct hlist_node *first = head->first;
    node->next  = first;
    node->pprev = &head->first;
    if (first)
        first->pprev = &node->next;
    head->first = node;
}

/*
 * hlist から node を削除する
 *    - *node->pprev (= 親の next ポインタ) を node->next に書き換え
 *    - もし node->next が存在すれば、その node->next->pprev を
 *      node->pprev (= 親の次のポインタのアドレス) にセットする
 *    - node 自身の next/pprev は NULL に戻しておく
 */
static inline void __hlist_del(struct hlist_node *node)
{
    struct hlist_node *next = node->next;
    struct hlist_node **pprev = node->pprev;

    if (next)
        next->pprev = pprev;
    *pprev = next;
    /* ノード自体は「リストから外された」状態に戻す */
    node->next  = NULL;
    node->pprev = NULL;
}

/* node がまだどこにもつながっていなければ削除しない */
static inline void hlist_del(struct hlist_node *node)
{
    if (node->pprev)
        __hlist_del(node);
}

/* node を別の head の先頭に移動 */
static inline void hlist_move_head(struct hlist_node *node, struct hlist_head *head)
{
    __hlist_del(node);
    hlist_add_head(node, head);
}

/*
 * hlist_for_each_entry_safe などを使いやすくするマクロ
 * 例: struct my_struct { int data; struct hlist_node node; };
 *      struct hlist_head bucket = HLIST_HEAD_INIT;
 *      struct my_struct *pos, *n;
 *      hlist_for_each_entry_safe(pos, n, &bucket, node) {
 *          // pos->data, pos->node を使える
 *      }
 */
#define hlist_entry(ptr, type, member) \
    ((type *)((char *)(ptr) - offsetof(type, member)))

#define hlist_for_each(pos, head) \
    for (pos = (head)->first; pos; pos = pos->next)

#define hlist_for_each_safe(pos, n, head)           \
    for (pos = (head)->first; pos && ((n) = pos->next, 1); pos = (n))

#define hlist_for_each_entry(pos, type, head, member)              \
    for (pos = hlist_entry((head)->first, type, member);           \
         &pos->member != NULL;                                     \
         pos = hlist_entry(pos->member.next, type, member))

#define hlist_for_each_entry_safe(pos, type, head, member, n)      \
    for (pos = hlist_entry((head)->first, type, member);           \
         &pos->member != NULL &&                                  \
            ((n) = hlist_entry(pos->member.next, type, member), 1); \
         pos = (n))

#endif /* _COMPAT_HLIST_H */
