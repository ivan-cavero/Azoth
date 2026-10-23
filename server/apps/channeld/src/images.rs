//! The content-service image placeholder.
//!
//! WHY A PLACEHOLDER AND NOT A 404
//! ===============================
//! The client fetches three `.dds` images from `client.content-service.amazongames.com` — the
//! maintenance modal and the news tile art. A 404 makes it **retry five times** and then show blank
//! white art, which is a worse outcome than a dark placeholder for the same bytes of effort.
//!
//! WHY A GENERATED FILE AND NOT REAL ART
//! ====================================
//! Real art is Phase 6 (our own object storage). What this module guarantees is the *contract*: the
//! route answers `200 image/dds` with a valid 256x256 uncompressed BGRA texture, so the client stops
//! retrying and the UI renders. Swapping the body for real art is a change to one function.
//!
//! The header is the DDS struct the format requires: magic, 124-byte header size, the CAPS/HEIGHT/
//! WIDTH/PITCH/PIXELFORMAT flags, the dimensions, the pitch, eleven reserved dwords, the pixel format
//! (32bpp BGRA with the four channel masks) and `DDSCAPS_TEXTURE`.

/// Width and height of the placeholder, in pixels.
const SIZE: usize = 256;

/// Build the placeholder DDS: a dark navy 256x256 BGRA texture.
#[must_use]
pub fn placeholder() -> Vec<u8> {
    let mut out = Vec::with_capacity(128 + SIZE * SIZE * 4);
    out.extend_from_slice(b"DDS ");
    out.extend_from_slice(&124u32.to_le_bytes()); // header size
    out.extend_from_slice(&0x0000_100Fu32.to_le_bytes()); // CAPS|HEIGHT|WIDTH|PITCH|PIXELFORMAT
    out.extend_from_slice(&(SIZE as u32).to_le_bytes()); // height
    out.extend_from_slice(&(SIZE as u32).to_le_bytes()); // width
    out.extend_from_slice(&((SIZE * 4) as u32).to_le_bytes()); // pitch
    out.extend_from_slice(&0u32.to_le_bytes()); // depth
    out.extend_from_slice(&0u32.to_le_bytes()); // mipmap count
    for _ in 0..11 {
        out.extend_from_slice(&0u32.to_le_bytes()); // reserved
    }
    out.extend_from_slice(&32u32.to_le_bytes()); // pixel format size
    out.extend_from_slice(&0x40u32.to_le_bytes()); // DDPF_RGB
    out.extend_from_slice(&0u32.to_le_bytes()); // four cc
    out.extend_from_slice(&32u32.to_le_bytes()); // bit count
    out.extend_from_slice(&0x00FF_0000u32.to_le_bytes()); // red mask
    out.extend_from_slice(&0x0000_FF00u32.to_le_bytes()); // green mask
    out.extend_from_slice(&0x0000_00FFu32.to_le_bytes()); // blue mask
    out.extend_from_slice(&0xFF00_0000u32.to_le_bytes()); // alpha mask
    out.extend_from_slice(&0x1000u32.to_le_bytes()); // DDSCAPS_TEXTURE
    for _ in 0..4 {
        out.extend_from_slice(&0u32.to_le_bytes()); // caps2..caps4, reserved2
    }
    // BGRA dark navy, four bytes per pixel.
    for _ in 0..(SIZE * SIZE) {
        out.extend_from_slice(&[0x30, 0x10, 0x08, 0xFF]);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_placeholder_is_a_valid_dds() {
        let bytes = placeholder();
        assert_eq!(&bytes[0..4], b"DDS ", "magic");
        assert_eq!(u32::from_le_bytes(bytes[4..8].try_into().expect("4")), 124);
        // 128-byte header plus SIZE*SIZE*4 of BGRA.
        assert_eq!(bytes.len(), 128 + SIZE * SIZE * 4);
    }

    #[test]
    fn the_dimensions_are_256_square() {
        let bytes = placeholder();
        let height = u32::from_le_bytes(bytes[12..16].try_into().expect("4"));
        let width = u32::from_le_bytes(bytes[16..20].try_into().expect("4"));
        assert_eq!((width, height), (256, 256));
    }

    #[test]
    fn the_pitch_matches_four_bytes_per_pixel() {
        let bytes = placeholder();
        let pitch = u32::from_le_bytes(bytes[20..24].try_into().expect("4"));
        assert_eq!(pitch, 256 * 4);
    }
}
