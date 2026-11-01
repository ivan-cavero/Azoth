//! Record framing and the bounds-checked byte cursor every codec borrows.
//!
//! A wire record is `00 01` (the type marker), then the prefix-varint message
//! type, then the message body. The Atlas cards model the *body*; this module
//! owns the marker and the cursor primitives, and nothing else. It never reads a
//! file and never plays a recording.

use core::fmt;

use crate::opaque::Opaque;

/// The two-byte marker that precedes the message type in a record.
pub const RECORD_TYPE_MARKER: [u8; 2] = [0x00, 0x01];

/// Largest value the measured prefix varint can carry (four continuation bytes).
pub(crate) const PREFIX_VARINT_MAX: u64 = (1 << 35) - 1;

/// Largest value the wide prefix varint can carry (seven continuation bytes).
pub(crate) const MASK_VARINT_MAX: u64 = (1 << 56) - 1;

/// A body that does not match the layout its Atlas card states.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum WireError {
    /// The body ended before a field was complete.
    Truncated {
        /// The field being read.
        field: &'static str,
        /// Bytes the field needs.
        need: usize,
        /// Bytes left in the body.
        have: usize,
    },
    /// A value is outside the bound the card states.
    OutOfRange {
        /// The field being read.
        field: &'static str,
        /// The largest value the card allows.
        max: u64,
        /// The value found.
        value: u64,
    },
    /// The body carried bytes after its last field.
    TrailingBytes {
        /// Bytes left unconsumed.
        remaining: usize,
    },
    /// A string field was not valid UTF-8.
    InvalidUtf8 {
        /// The field being read.
        field: &'static str,
    },
    /// A fixed-width string is longer than its width.
    ValueTooLong {
        /// The field being written.
        field: &'static str,
        /// The fixed width in bytes.
        max: usize,
        /// The length offered.
        len: usize,
    },
    /// A varint did not terminate inside its measured maximum width.
    VarintTooLong,
    /// A strict zero-or-one flag byte held some other value.
    NotBoolean {
        /// The field holding the offending value.
        field: &'static str,
        /// The value found.
        value: u8,
    },
    /// A two-level presence mask set a bit the card does not declare.
    UnknownPresence {
        /// Which mask the bit belongs to, e.g. `"group"` or `"member"`.
        what: &'static str,
        /// The index whose bit was set.
        index: u64,
    },
    /// A component family was asked for a state type index it does not carry.
    UnsupportedType {
        /// The type index the caller asked for.
        type_index: u64,
    },
}

impl fmt::Display for WireError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated { field, need, have } => {
                write!(f, "field {field} needs {need} byte(s), {have} remain")
            }
            Self::OutOfRange { field, max, value } => {
                write!(f, "field {field} value {value} exceeds max {max}")
            }
            Self::TrailingBytes { remaining } => {
                write!(f, "{remaining} byte(s) after the last field")
            }
            Self::InvalidUtf8 { field } => write!(f, "field {field} is not valid UTF-8"),
            Self::ValueTooLong { field, max, len } => {
                write!(f, "field {field} holds {max} byte(s), got {len}")
            }
            Self::VarintTooLong => write!(f, "varint is longer than its maximum width"),
            Self::NotBoolean { field, value } => {
                write!(f, "field {field} is {value}, not zero or one")
            }
            Self::UnknownPresence { what, index } => {
                write!(f, "{what} mask bit {index} names no declared {what}")
            }
            Self::UnsupportedType { type_index } => {
                write!(
                    f,
                    "state type {type_index} is not one this component carries"
                )
            }
        }
    }
}

impl std::error::Error for WireError {}

/// Number of bytes the measured prefix varint uses for `value`.
fn prefix_varint_size(value: u64) -> usize {
    if value < 0x80 {
        1
    } else if value < (1 << 14) {
        2
    } else if value < (1 << 21) {
        3
    } else if value < (1 << 28) {
        4
    } else {
        5
    }
}

/// A bounds-checked cursor over one message body.
#[derive(Debug, Clone)]
pub struct Reader<'a> {
    body: &'a [u8],
    offset: usize,
}

impl<'a> Reader<'a> {
    /// Start at the first body byte.
    pub const fn new(body: &'a [u8]) -> Self {
        Self { body, offset: 0 }
    }

    /// Bytes consumed so far.
    pub const fn position(&self) -> usize {
        self.offset
    }

    /// Bytes still to consume.
    pub const fn remaining(&self) -> usize {
        self.body.len() - self.offset
    }

    /// True when the cursor is exactly at the end of the body.
    pub const fn is_empty(&self) -> bool {
        self.offset == self.body.len()
    }

    /// Consume exactly `len` bytes.
    pub fn take(&mut self, field: &'static str, len: usize) -> Result<&'a [u8], WireError> {
        let end = self.offset.saturating_add(len);
        if end > self.body.len() {
            return Err(WireError::Truncated {
                field,
                need: len,
                have: self.body.len() - self.offset,
            });
        }
        let raw = &self.body[self.offset..end];
        self.offset = end;
        Ok(raw)
    }

    fn take_array<const N: usize>(&mut self, field: &'static str) -> Result<[u8; N], WireError> {
        let raw = self.take(field, N)?;
        raw.try_into().map_err(|_| WireError::Truncated {
            field,
            need: N,
            have: raw.len(),
        })
    }

    /// The body must have no bytes left.
    pub fn finish(&self) -> Result<(), WireError> {
        if self.is_empty() {
            Ok(())
        } else {
            Err(WireError::TrailingBytes {
                remaining: self.remaining(),
            })
        }
    }

    /// Read one byte.
    pub fn u8(&mut self, field: &'static str) -> Result<u8, WireError> {
        Ok(self.take_array::<1>(field)?[0])
    }

    /// Read one signed byte.
    pub fn i8(&mut self, field: &'static str) -> Result<i8, WireError> {
        Ok(i8::from_be_bytes(self.take_array::<1>(field)?))
    }

    /// Read a big-endian `u16`.
    pub fn u16be(&mut self, field: &'static str) -> Result<u16, WireError> {
        Ok(u16::from_be_bytes(self.take_array::<2>(field)?))
    }

    /// Read a little-endian `u16`.
    pub fn u16le(&mut self, field: &'static str) -> Result<u16, WireError> {
        Ok(u16::from_le_bytes(self.take_array::<2>(field)?))
    }

    /// Read a big-endian `i16`.
    pub fn i16be(&mut self, field: &'static str) -> Result<i16, WireError> {
        Ok(i16::from_be_bytes(self.take_array::<2>(field)?))
    }

    /// Read a big-endian `u32`.
    pub fn u32be(&mut self, field: &'static str) -> Result<u32, WireError> {
        Ok(u32::from_be_bytes(self.take_array::<4>(field)?))
    }

    /// Read a little-endian `u32`.
    pub fn u32le(&mut self, field: &'static str) -> Result<u32, WireError> {
        Ok(u32::from_le_bytes(self.take_array::<4>(field)?))
    }

    /// Read a big-endian `i32`.
    pub fn i32be(&mut self, field: &'static str) -> Result<i32, WireError> {
        Ok(i32::from_be_bytes(self.take_array::<4>(field)?))
    }

    /// Read a big-endian `u64`.
    pub fn u64be(&mut self, field: &'static str) -> Result<u64, WireError> {
        Ok(u64::from_be_bytes(self.take_array::<8>(field)?))
    }

    /// Read a little-endian `u64`.
    pub fn u64le(&mut self, field: &'static str) -> Result<u64, WireError> {
        Ok(u64::from_le_bytes(self.take_array::<8>(field)?))
    }

    /// Read a big-endian `i64`.
    pub fn i64be(&mut self, field: &'static str) -> Result<i64, WireError> {
        Ok(i64::from_be_bytes(self.take_array::<8>(field)?))
    }

    /// Read a big-endian `f32`.
    pub fn f32be(&mut self, field: &'static str) -> Result<f32, WireError> {
        Ok(f32::from_be_bytes(self.take_array::<4>(field)?))
    }

    /// Read a little-endian `f32`.
    pub fn f32le(&mut self, field: &'static str) -> Result<f32, WireError> {
        Ok(f32::from_le_bytes(self.take_array::<4>(field)?))
    }

    /// Read a big-endian `f64`.
    pub fn f64be(&mut self, field: &'static str) -> Result<f64, WireError> {
        Ok(f64::from_be_bytes(self.take_array::<8>(field)?))
    }

    /// Read one boolean byte; any non-zero byte is true.
    pub fn bool_byte(&mut self, field: &'static str) -> Result<bool, WireError> {
        Ok(self.u8(field)? != 0)
    }

    /// Read the measured Javelin prefix varint.
    pub fn prefix_varint(&mut self, field: &'static str) -> Result<u64, WireError> {
        let first = self.u8(field)?;
        let n = first.leading_ones().min(4) as usize;
        if n == 0 {
            return Ok(u64::from(first));
        }
        let raw = self.take(field, n)?;
        let mut continuation = 0u64;
        for (index, byte) in raw.iter().enumerate() {
            continuation |= u64::from(*byte) << (8 * index as u32);
        }
        let shift = 7 - n as u32;
        Ok((continuation << shift) | u64::from(first & ((1u8 << shift) - 1)))
    }

    /// Read the wide prefix varint the ALC presence-mask reader uses.
    ///
    /// It is the same encoding as [`Self::prefix_varint`] with a larger ceiling:
    /// the leading 1-bits of the first byte give up to seven continuation bytes,
    /// so a mask can be 56 bits wide. A first byte of `0xff` (eight leading ones)
    /// is refused, never guessed.
    ///
    /// # Errors
    /// Returns [`WireError::Truncated`] when the sequence is incomplete, or
    /// [`WireError::VarintTooLong`] when the first byte carries eight leading ones.
    pub fn mask_varint(&mut self, field: &'static str) -> Result<u64, WireError> {
        let first = self.u8(field)?;
        let n = first.leading_ones() as usize;
        if n > 7 {
            return Err(WireError::VarintTooLong);
        }
        if n == 0 {
            return Ok(u64::from(first));
        }
        let raw = self.take(field, n)?;
        let mut continuation = 0u64;
        for (index, byte) in raw.iter().enumerate() {
            continuation |= u64::from(*byte) << (8 * index as u32);
        }
        let shift = 7 - n as u32;
        Ok((continuation << shift) | u64::from(first & ((1u8 << shift) - 1)))
    }

    /// Read a plain LEB128 varint.
    pub fn varint(&mut self, field: &'static str) -> Result<u64, WireError> {
        let mut result = 0u64;
        let mut shift = 0u32;
        loop {
            let byte = self.u8(field)?;
            result |= u64::from(byte & 0x7f) << shift;
            if byte & 0x80 == 0 {
                return Ok(result);
            }
            shift += 7;
            if shift > 63 {
                return Err(WireError::VarintTooLong);
            }
        }
    }

    /// Read a prefix-varint-counted string.
    pub fn prefixed_string(&mut self, field: &'static str) -> Result<String, WireError> {
        let len = self.prefixed_len(field)?;
        let raw = self.take(field, len)?;
        core::str::from_utf8(raw)
            .map(str::to_owned)
            .map_err(|_| WireError::InvalidUtf8 { field })
    }

    /// Read a fixed-width string, trimming trailing NUL padding.
    pub fn fixed_string(&mut self, field: &'static str, width: usize) -> Result<String, WireError> {
        let raw = self.take(field, width)?;
        let trimmed = match raw.iter().position(|byte| *byte == 0) {
            Some(end) => &raw[..end],
            None => raw,
        };
        core::str::from_utf8(trimmed)
            .map(str::to_owned)
            .map_err(|_| WireError::InvalidUtf8 { field })
    }

    /// Read a prefix-varint-counted raw run, tagged with its Atlas id.
    pub fn prefixed_opaque(
        &mut self,
        field: &'static str,
        id: &'static str,
    ) -> Result<Opaque, WireError> {
        let len = self.prefixed_len(field)?;
        let raw = self.take(field, len)?;
        Ok(Opaque::new(id, raw.to_vec()))
    }

    /// Read a fixed-width raw run, tagged with its Atlas id.
    pub fn opaque(
        &mut self,
        field: &'static str,
        id: &'static str,
        width: usize,
    ) -> Result<Opaque, WireError> {
        let raw = self.take(field, width)?;
        Ok(Opaque::new(id, raw.to_vec()))
    }

    fn prefixed_len(&mut self, field: &'static str) -> Result<usize, WireError> {
        let len = self.prefix_varint(field)?;
        usize::try_from(len).map_err(|_| WireError::OutOfRange {
            field,
            max: usize::MAX as u64,
            value: len,
        })
    }
}

/// A builder that appends one message body to a caller's buffer.
#[derive(Debug)]
pub struct Writer<'a> {
    out: &'a mut Vec<u8>,
}

impl<'a> Writer<'a> {
    /// Append to `out`.
    pub fn new(out: &'a mut Vec<u8>) -> Self {
        Self { out }
    }

    /// Write one byte.
    pub fn u8(&mut self, value: u8) {
        self.out.push(value);
    }

    /// Write a run of bytes the caller already holds in wire order.
    ///
    /// Only for a field whose card states a fixed byte width; a variable run is
    /// written with [`Self::prefixed_opaque`] so it keeps its length prefix.
    pub fn raw(&mut self, bytes: &[u8]) {
        self.out.extend_from_slice(bytes);
    }

    /// Write one signed byte.
    pub fn i8(&mut self, value: i8) {
        self.out.push(value as u8);
    }

    /// Write a big-endian `u16`.
    pub fn u16be(&mut self, value: u16) {
        self.out.extend_from_slice(&value.to_be_bytes());
    }

    /// Write a little-endian `u16`.
    pub fn u16le(&mut self, value: u16) {
        self.out.extend_from_slice(&value.to_le_bytes());
    }

    /// Write a big-endian `i16`.
    pub fn i16be(&mut self, value: i16) {
        self.out.extend_from_slice(&value.to_be_bytes());
    }

    /// Write a big-endian `u32`.
    pub fn u32be(&mut self, value: u32) {
        self.out.extend_from_slice(&value.to_be_bytes());
    }

    /// Write a little-endian `u32`.
    pub fn u32le(&mut self, value: u32) {
        self.out.extend_from_slice(&value.to_le_bytes());
    }

    /// Write a big-endian `i32`.
    pub fn i32be(&mut self, value: i32) {
        self.out.extend_from_slice(&value.to_be_bytes());
    }

    /// Write a big-endian `u64`.
    pub fn u64be(&mut self, value: u64) {
        self.out.extend_from_slice(&value.to_be_bytes());
    }

    /// Write a little-endian `u64`.
    pub fn u64le(&mut self, value: u64) {
        self.out.extend_from_slice(&value.to_le_bytes());
    }

    /// Write a big-endian `i64`.
    pub fn i64be(&mut self, value: i64) {
        self.out.extend_from_slice(&value.to_be_bytes());
    }

    /// Write a big-endian `f32`.
    pub fn f32be(&mut self, value: f32) {
        self.out.extend_from_slice(&value.to_be_bytes());
    }

    /// Write a little-endian `f32`.
    pub fn f32le(&mut self, value: f32) {
        self.out.extend_from_slice(&value.to_le_bytes());
    }

    /// Write a big-endian `f64`.
    pub fn f64be(&mut self, value: f64) {
        self.out.extend_from_slice(&value.to_be_bytes());
    }

    /// Write the measured Javelin prefix varint.
    pub fn prefix_varint(&mut self, value: u64) -> Result<(), WireError> {
        if value > PREFIX_VARINT_MAX {
            return Err(WireError::OutOfRange {
                field: "prefix_varint",
                max: PREFIX_VARINT_MAX,
                value,
            });
        }
        if value < 0x80 {
            self.out.push(value as u8);
            return Ok(());
        }
        let n = prefix_varint_size(value) - 1;
        let shift = 7 - n;
        let low = (value & ((1u64 << shift) - 1)) as u8;
        let high = value >> shift;
        let leading = (((0xffu16 << (8 - n)) & 0xff) as u8) | low;
        self.out.push(leading);
        self.out.extend_from_slice(&high.to_le_bytes()[..n]);
        Ok(())
    }

    /// Write the wide prefix varint the ALC presence-mask writer uses.
    ///
    /// # Errors
    /// Returns [`WireError::OutOfRange`] when `value` needs more than seven
    /// continuation bytes.
    pub fn mask_varint(&mut self, value: u64) -> Result<(), WireError> {
        if value > MASK_VARINT_MAX {
            return Err(WireError::OutOfRange {
                field: "mask_varint",
                max: MASK_VARINT_MAX,
                value,
            });
        }
        if value < 0x80 {
            self.out.push(value as u8);
            return Ok(());
        }
        let mut n = 1usize;
        while n < 7 && value >= (1u64 << (7 + 7 * n)) {
            n += 1;
        }
        let shift = 7 - n as u32;
        let low = (value & ((1u64 << shift) - 1)) as u8;
        let high = value >> shift;
        let leading = (((0xffu16 << (8 - n)) & 0xff) as u8) | low;
        self.out.push(leading);
        self.out.extend_from_slice(&high.to_le_bytes()[..n]);
        Ok(())
    }

    /// Write a plain LEB128 varint.
    pub fn varint(&mut self, value: u64) {
        let mut rest = value;
        loop {
            let byte = (rest & 0x7f) as u8;
            rest >>= 7;
            if rest == 0 {
                self.out.push(byte);
                return;
            }
            self.out.push(byte | 0x80);
        }
    }

    /// Write a prefix-varint-counted string.
    pub fn prefixed_string(&mut self, value: &str) -> Result<(), WireError> {
        self.prefix_varint(value.len() as u64)?;
        self.out.extend_from_slice(value.as_bytes());
        Ok(())
    }

    /// Write a fixed-width string, padding with NUL.
    pub fn fixed_string(&mut self, value: &str, width: usize) -> Result<(), WireError> {
        let raw = value.as_bytes();
        if raw.len() > width {
            return Err(WireError::ValueTooLong {
                field: "fixed_string",
                max: width,
                len: raw.len(),
            });
        }
        self.out.extend_from_slice(raw);
        self.out.resize(self.out.len() + (width - raw.len()), 0);
        Ok(())
    }

    /// Write a prefix-varint-counted raw run.
    pub fn prefixed_opaque(&mut self, value: &Opaque) -> Result<(), WireError> {
        self.prefix_varint(value.len() as u64)?;
        self.out.extend_from_slice(value.as_slice());
        Ok(())
    }

    /// Write a fixed-width raw run.
    pub fn opaque(&mut self, value: &Opaque) {
        self.out.extend_from_slice(value.as_slice());
    }
}
