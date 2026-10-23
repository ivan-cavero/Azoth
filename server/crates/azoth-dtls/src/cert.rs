//! The server's DTLS identity: a self-signed RSA certificate with `CN=New World`.
//!
//! WHY RSA, AND WHY THE SUBJECT DOES NOT MATTER
//! ============================================
//! The only suite the client offers is `0xC030` `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`
//! (`docs/PLAN-backend-rust.md` §0.3), so the certificate's key **must** be RSA — an ECDSA key
//! cannot sign the `ServerKeyExchange` for an `ECDHE_RSA` suite. Everything else about the
//! certificate is cosmetic: the client's verify path is patched on disk
//! (`CMP [rdi+0x288],0` at `0x145DCF9ED`, patch `e9 1a 01 00 00 90`, `STATUS.md` 2026-10-22),
//! so no authority we could control would ever validate it. `CN=New World` is kept because the
//! prototype uses it (`services/world/src/azoth_world/rep.py::make_self_signed_cert`) and a log
//! line that says the same thing in both implementations is worth having.
//!
//! THIS IS A BEHAVIOUR PORT, NOT A REDESIGN
//! ========================================
//! [`Identity::load_or_generate`] reproduces the prototype exactly: the same two file names
//! (`rep.crt`, `rep.key`), reuse when both exist, and on generation an RSA-2048 key, serial
//! number = Unix seconds, `notBefore` = now, `notAfter` = now + 10 years, issuer = subject, and
//! a SHA-256 self-signature. That is deliberate — a running Python world server and a running
//! Rust world server can share a directory, and the certificate that works for one works for
//! the other. Changing the serial scheme or the validity window would be a change with no
//! observable benefit and one observable cost: a second certificate on disk.

use std::fs;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use openssl::asn1::Asn1Time;
use openssl::bn::BigNum;
use openssl::hash::MessageDigest;
use openssl::pkey::{PKey, Private};
use openssl::rsa::Rsa;
use openssl::x509::{X509, X509NameBuilder};

use crate::DtlsError;

/// The certificate's file name. Matches the prototype so a shared `certs/` directory is reused.
const CERT_FILE: &str = "rep.crt";

/// The private key's file name. Matches the prototype, for the same reason.
const KEY_FILE: &str = "rep.key";

/// The key size the prototype generates. 2048 bits is what OpenSSL 3's default security level
/// accepts and what an `ECDHE_RSA` suite needs to sign with; larger costs handshake time for no
/// benefit the client can observe.
const KEY_BITS: u32 = 2048;

/// The validity window the prototype uses: ten years, so a long-lived private server never has
/// to reissue.
const VALID_DAYS: u32 = 3650;

/// A self-signed RSA certificate and its private key, in PEM.
///
/// Generic, not DER, because the prototype writes PEM and a shared `certs/` directory is the
/// point.
#[derive(Clone, Debug)]
pub struct Identity {
    /// The certificate, PEM-encoded.
    pub cert_pem: Vec<u8>,
    /// The matching private key, PEM-encoded (unencrypted, because OpenSSL reads it without a
    /// passphrase callback and the file lives in an ignored local directory).
    pub key_pem: Vec<u8>,
}

impl Identity {
    /// Load the pair from `dir`, generating an RSA-2048 `CN=New World` pair if absent.
    ///
    /// The check is "both files exist", exactly as the prototype does it: a directory with only
    /// one of the two is treated as absent and overwritten, because half a key pair cannot
    /// handshake and there is nothing to preserve.
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::Io`] if `dir` cannot be created or a file cannot be written, and
    /// [`DtlsError::OpenSsl`] if key generation or signing fails.
    pub fn load_or_generate(dir: &Path) -> Result<Self, DtlsError> {
        let cert_path = dir.join(CERT_FILE);
        let key_path = dir.join(KEY_FILE);
        if cert_path.exists() && key_path.exists() {
            return Ok(Self {
                cert_pem: fs::read(cert_path)?,
                key_pem: fs::read(key_path)?,
            });
        }

        let self_signed = Self::generate()?;
        fs::create_dir_all(dir)?;
        fs::write(&cert_path, &self_signed.cert_pem)?;
        fs::write(&key_path, &self_signed.key_pem)?;
        Ok(self_signed)
    }

    /// Generate a fresh RSA-2048 `CN=New World` pair without touching the filesystem.
    ///
    /// Separate from [`Identity::load_or_generate`] so a caller that keeps its identity somewhere
    /// else (an in-memory test, a secret store) is not forced to write PEM files first.
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::OpenSsl`] if key generation or signing fails.
    pub fn generate() -> Result<Self, DtlsError> {
        let key = PKey::from_rsa(Rsa::generate(KEY_BITS)?)?;

        let mut subject = X509NameBuilder::new()?;
        subject.append_entry_by_text("CN", "New World")?;
        let subject = subject.build();

        let mut builder = X509::builder()?;
        builder.set_subject_name(&subject)?;
        builder.set_issuer_name(&subject)?;
        builder.set_pubkey(&key)?;
        let serial = serial_number()?;
        builder.set_serial_number(&serial)?;
        let not_before = Asn1Time::days_from_now(0)?;
        builder.set_not_before(&not_before)?;
        let not_after = Asn1Time::days_from_now(VALID_DAYS)?;
        builder.set_not_after(&not_after)?;
        builder.sign(&key, MessageDigest::sha256())?;

        Ok(Self {
            cert_pem: builder.build().to_pem()?,
            key_pem: key.private_key_to_pem_pkcs8()?,
        })
    }

    /// Parse [`Identity::cert_pem`] into an `X509`.
    ///
    /// Parsed on demand rather than stored, so the public shape stays two byte buffers and a
    /// caller can round-trip it through any store it likes.
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::OpenSsl`] if the bytes are not a PEM certificate.
    pub fn certificate(&self) -> Result<X509, DtlsError> {
        Ok(X509::from_pem(&self.cert_pem)?)
    }

    /// Parse [`Identity::key_pem`] into a private key.
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::OpenSsl`] if the bytes are not an unencrypted PEM private key.
    pub fn private_key(&self) -> Result<PKey<Private>, DtlsError> {
        Ok(PKey::private_key_from_pem(&self.key_pem)?)
    }
}

/// The prototype's serial number: Unix seconds. Not random, and not required to be — the client
/// validates nothing. It only has to be a positive integer that changes when the pair is
/// regenerated, so a log reader can tell two certificates apart.
fn serial_number() -> Result<openssl::asn1::Asn1Integer, DtlsError> {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    // A zero serial is invalid per RFC 5280, so a clock that reports the epoch is floored to 1.
    Ok(BigNum::from_dec_str(&secs.max(1).to_string())?.to_asn1_integer()?)
}
