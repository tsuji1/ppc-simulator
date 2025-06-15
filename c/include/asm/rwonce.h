#ifndef _ASM_RWONCE_H
#define _ASM_RWONCE_H
/*
 * 最低限の READ/WRITE_ONCE。
 * ユーザ空間なので strict barrier は不要。
 */
#define READ_ONCE(x)        (*(volatile typeof(x) *)&(x))
#define WRITE_ONCE(x, v)    ({                            \
        (*(volatile typeof(x) *)&(x)) = (v);              \
        (void)0;                                          \
})
#endif /* _ASM_RWONCE_H */
