#!/usr/bin/env bash
set -euo pipefail
set -x

LINUX=$HOME/linux
PROJ=$HOME/osada-ppc-simulator
GCC_INC=$(gcc -print-file-name=include)
GLIBC_INC=/usr/include
GLIBC_ARCH_INC=/usr/include/$(gcc -dumpmachine)

# コンパイル共通フラグ（カーネルコード用）
KCFLAGS="
 -nostdinc
 -include $LINUX/include/generated/autoconf.h
 -include $LINUX/include/linux/kconfig.h
 -isystem $GCC_INC
 -isystem $GLIBC_INC
 -isystem $GLIBC_ARCH_INC
 -I$LINUX/include -I$LINUX/arch/x86/include
 -I$LINUX/include/generated -I$LINUX/arch/x86/include/generated
 -I$LINUX/include/uapi      -I$LINUX/arch/x86/include/uapi
 -I$LINUX/include/generated/uapi -I$LINUX/arch/x86/include/generated/uapi
 -I$PROJ/c/include
 -D__KERNEL__
 -DKBUILD_MODNAME=\"fib_trie_user\"
 -Og -g -Wall
"
KCFLAGS+=" -DCONFIG_TRACEPOINTS=0 "

# 1) fib_trie.c だけをカーネル風にビルド
gcc $KCFLAGS -c $PROJ/c/src/fib_trie.c -o fib_trie.user.o

#  -I/usr/src/linux-headers-6.11.0-25-generic/include \ 
# 2) wrapper.c は純ユーザ空間なので普通に
gcc -I$PROJ/c/include -Og -g -Wall -c $PROJ/c/src/wrapper.c -o wrapper.o 
gcc -I$PROJ/c/include -Og -g -Wall \
    -c $PROJ/c/stubs.c -o stubs.o

# 3) テストプログラムとリンク
gcc -I$PROJ/c/include $PROJ/quick_test.c fib_trie.user.o wrapper.o stubs.o -o quick_test
