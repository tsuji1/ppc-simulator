#ifndef _COMPAT_RCU_H
#define _COMPAT_RCU_H

/*
 * カーネルの <linux/rcupdate.h> にある rcu_head と同じサイズ・レイアウトの定義
 *
 *  kernel/src/include/linux/rcupdate.h (要約):
 *    struct rcu_head {
 *        struct rcu_head *next;
 *        void (*func)(struct rcu_head *rcu);
 *    };
 *
 *  上記は「ポインタ＋関数ポインタ」の 2 ポインタ分（合計 16 バイト on x86_64）
 *  なので、ユーザ空間でも同様に定義してやれば同じサイズになります。
 */

/* コールバック関数の型 */
typedef void (*rcu_callback_t)(struct rcu_head *rcu);

/* rcu_head のスタブ定義 */
struct rcu_head {
    struct rcu_head *next;
    rcu_callback_t   func;
};

#endif /* _COMPAT_RCU_H */
