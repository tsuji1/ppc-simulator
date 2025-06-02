#include <stdint.h> 
#ifdef __cplusplus
extern "C" {
#endif
struct lctrie;
struct lctrie *lctrie_new(void);
void           lctrie_insert(struct lctrie *t, uint32_t prefix, uint8_t plen);
int            lctrie_lookup(struct lctrie *t, uint32_t addr);
void           lctrie_free(struct lctrie *t);
#ifdef __cplusplus
}
#endif
