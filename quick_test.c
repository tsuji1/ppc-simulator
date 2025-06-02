/* quick_test.c */
#include <stdio.h>
#include "lctrie.h"

int main(void){
    struct lctrie *t = lctrie_new();
    lctrie_insert(t, 0x0a000000, 24);   /* 10.0.0.0/24 */
    printf("lookup 10.0.0.1 : %s\n",
           lctrie_lookup(t, 0x0a000001) ? "hit" : "miss");
    lctrie_free(t);
    return 0;
}
