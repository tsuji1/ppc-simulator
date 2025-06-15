/* quick_test.c */
#include <stdio.h>
#include "lctrie.h"
//cのlctrieを使用するテストのプログラム
int main(void){
    struct lctrie *t = lctrie_new();
    lctrie_insert(t, 0x0a000000, 24, 11111);   /* 10.0.0.0/24 */
    lctrie_insert(t, 0x0a000000, 25, 22222);   /* 10.0.0.0/24 */

    struct custom_result res = lctrie_lookup(t, 0x0000001);
    printf("lookup 10.0.0.1 : %s\n",
            res.found ? "hit" : "miss");
    printf("prefix: %u.%u.%u.%u/%u, custom_id: %u\n",
            (res.prefix >> 24) & 0xff,
            (res.prefix >> 16) & 0xff,
            (res.prefix >> 8) & 0xff,
            res.prefix & 0xff,
            res.prefixlen,
            res.custom_id);
    lctrie_free(t);
    return 0;
}
