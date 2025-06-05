#include <stdint.h> 
#include <netinet/in.h>      /* htonl / ntohl 用 */
#include <linux/types.h>
#include <asm/byteorder.h>
#include <linux/ip.h>
#include <stdbool.h>
#ifdef __cplusplus
extern "C" {
#endif
struct lctrie;
struct custom_result
{
   unsigned char prefixlen; 
   uint32_t custom_id;
   uint32_t prefix; /* Store network byte order address */
   bool found;
};
struct lctrie *lctrie_new(void);

void           lctrie_insert(struct lctrie *t, uint32_t prefix, uint8_t plen, uint32_t custom_id);
struct custom_result lctrie_lookup(struct lctrie *t, uint32_t addr );
void           lctrie_free(struct lctrie *t);
#ifdef __cplusplus
}
#endif
