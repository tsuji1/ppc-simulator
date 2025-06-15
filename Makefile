# Makefile for placing all outputs under osada-ppc-simulator/c/
# ────────────────────────────────────────────────────────────────────

LINUX           := $(HOME)/linux
PROJ            := $(HOME)/osada-ppc-simulator
GCC_INC         := $(shell gcc -print-file-name=include)
GLIBC_INC       := /usr/include
GLIBC_ARCH_INC  := /usr/include/$(shell gcc -dumpmachine)

CC              := gcc
AR              := ar rcs

# カーネル風にビルドするときの CFLAGS
KCFLAGS  := -nostdinc \
            -include $(LINUX)/include/generated/autoconf.h \
            -include $(LINUX)/include/linux/kconfig.h \
            -isystem $(GCC_INC) \
            -isystem $(GLIBC_INC) \
            -isystem $(GLIBC_ARCH_INC) \
            -I$(LINUX)/include \
            -I$(LINUX)/arch/x86/include \
            -I$(LINUX)/include/generated \
            -I$(LINUX)/arch/x86/include/generated \
            -I$(LINUX)/include/uapi \
            -I$(LINUX)/arch/x86/include/uapi \
            -I$(LINUX)/include/generated/uapi \
            -I$(LINUX)/arch/x86/include/generated/uapi \
            -I$(PROJ)/c/include \
            -D__KERNEL__ \
            -DKBUILD_MODNAME=\"fib_trie_user\" \
            -Og -g -Wall \
            -DCONFIG_TRACEPOINTS=0

# ユーザ空間用 CFLAGS（wrapper.c, stubs.c, quick_test.c）
UFLAGS   := -I$(PROJ)/c/include -Og -g -Wall

# 出力ディレクトリ（すべてここに置く）
OUTDIR   := $(PROJ)/c

# 各ターゲットファイルのパス
KOBJ      := $(OUTDIR)/fib_trie.user.o
WOBJ      := $(OUTDIR)/wrapper.o
SOBJ      := $(OUTDIR)/stubs.o

STATIC_LIB := $(OUTDIR)/liblctrie.a
SHARED_LIB := $(OUTDIR)/liblctrie.so
TEST_BIN   := $(OUTDIR)/quick_test

.PHONY: all static shared quick_test clean

# ─────────────────────────────────────────────────────────────
# デフォルト target: static, shared, quick_test をまとめて生成
# ─────────────────────────────────────────────────────────────
all: static shared quick_test

# ─────────────────────────────────────────────────────────────
# 1) fib_trie.user.o を kernel‐style（-fPIC 付き）でビルド
# ─────────────────────────────────────────────────────────────
$(KOBJ): $(PROJ)/c/src/fib_trie.c
	$(CC) $(KCFLAGS) -fPIC -c $< -o $@

# ─────────────────────────────────────────────────────────────
# 2) wrapper.o をユーザ空間（-fPIC 付き）でビルド
# ─────────────────────────────────────────────────────────────
$(WOBJ): $(PROJ)/c/src/wrapper.c
	$(CC) $(UFLAGS) -fPIC -c $< -o $@

# ─────────────────────────────────────────────────────────────
# 3) stubs.o をユーザ空間（-fPIC 付き）でビルド
# ─────────────────────────────────────────────────────────────
$(SOBJ): $(PROJ)/c/stubs.c
	$(CC) $(UFLAGS) -fPIC -c $< -o $@

# ─────────────────────────────────────────────────────────────
# 4) 静的ライブラリ liblctrie.a を作成
# ─────────────────────────────────────────────────────────────
static: $(STATIC_LIB)

$(STATIC_LIB): $(KOBJ) $(WOBJ) $(SOBJ)
	$(AR) $@ $(KOBJ) $(WOBJ) $(SOBJ)

# ─────────────────────────────────────────────────────────────
# 5) 共有ライブラリ liblctrie.so を作成
# ─────────────────────────────────────────────────────────────
shared: $(SHARED_LIB)

$(SHARED_LIB): $(KOBJ) $(WOBJ) $(SOBJ)
	$(CC) -shared -o $@ $(KOBJ) $(WOBJ) $(SOBJ)

# ─────────────────────────────────────────────────────────────
# 6) quick_test をビルドして $(OUTDIR) に置く
#    （静的ライブラリ liblctrie.a にリンク）
# ─────────────────────────────────────────────────────────────
quick_test: $(TEST_BIN)

$(TEST_BIN): quick_test.c $(STATIC_LIB)
	$(CC) $(UFLAGS) \
	    quick_test.c \
	    -L$(OUTDIR) -llctrie \
	    -o $@

# ─────────────────────────────────────────────────────────────
# 7) クリーンアップ: すべての出力ファイルを削除
# ─────────────────────────────────────────────────────────────
clean:
	rm -f $(KOBJ) $(WOBJ) $(SOBJ) $(STATIC_LIB) $(SHARED_LIB) $(TEST_BIN)
