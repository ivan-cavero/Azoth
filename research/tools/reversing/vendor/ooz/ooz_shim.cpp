// Tiny ctypes shim over ooz's Kraken decoder.
//
// The ooz decompressor may write up to SAFE_SPACE (64) bytes past the end of
// the destination buffer (see the warning above Kraken_Decompress in
// kraken.cpp). This shim allocates dst_len + 64 itself, decodes, and the
// caller truncates to dst_len. All allocation stays inside the shim so the
// ctypes caller never has to guess the padding.
//
// Source provenance: github.com/powzix/ooz @ 1d1051adab00420707bc0b59f9002cac932d7985
// (zlib license). Vendored, not modified.

#include "kraken.h"
#include <cstring>

#define OOZ_SAFE_SPACE 64

extern "C" __declspec(dllexport)
int ooz_decompress(const unsigned char *src, size_t src_len,
                   unsigned char *dst, size_t dst_len,
                   size_t *written) {
    unsigned char *buf = (unsigned char *)malloc(dst_len + OOZ_SAFE_SPACE);
    if (!buf)
        return -100;
    int ret = Kraken_Decompress(src, src_len, buf, dst_len);
    if (ret < 0) {
        free(buf);
        return ret;
    }
    size_t n = (size_t)ret;
    if (n > dst_len)
        n = dst_len;
    memcpy(dst, buf, n);
    *written = n;
    free(buf);
    return 0;
}
