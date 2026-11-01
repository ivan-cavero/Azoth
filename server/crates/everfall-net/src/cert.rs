//! RSA 2048 self-signed certificate for the DTLS server.
//!
//! # Why RSA, and why this is measured
//!
//! The certificate is **not** an implementation detail here; it is the whole
//! reason OpenSSL replaced `dimpl`. With `dimpl` bound on the REP port and a
//! clean client run against it, the client sent **twelve 159-byte
//! `ClientHellos`** and `dimpl` produced no flight at all, ending in
//! `dtls error: timeout: connect`. The client's DTLS works against the Python
//! lab world, which signs with an **RSA 2048** certificate (`CN=New World`),
//! and `dimpl` lists RSA as an explicit non-goal. So the server must present an
//! RSA certificate, and this module mints one.
//!
//! # Shape
//!
//! It matches `services/world/src/azoth_world/rep.py` (`make_self_signed_cert`):
//! RSA 2048, `CN=New World`, subject == issuer, serial number from the current
//! unix time, valid for ten years, signed with SHA-256.
//!
//! # Provenance
//!
//! The certificate and key are generated **fresh in memory at process start**,
//! never read from disk and never written to it. `RsaIdentity::generate` draws
//! a fresh RSA key from OpenSSL's RNG and builds the certificate around it, so
//! no private key is ever committed or logged.

use openssl::asn1::{Asn1Integer, Asn1Time};
use openssl::bn::BigNum;
use openssl::error::ErrorStack;
use openssl::hash::MessageDigest;
use openssl::nid::Nid;
use openssl::pkey::{PKey, PKeyRef, Private};
use openssl::rsa::Rsa;
use openssl::x509::{X509, X509Builder, X509NameBuilder, X509Ref};

/// Subject and issuer common name, matching the Python lab certificate.
const COMMON_NAME: &str = "New World";

/// RSA modulus size in bits. The client's pinned trust root is RSA 2048.
const RSA_BITS: u32 = 2048;

/// Validity window, matching `make_self_signed_cert` (ten years).
const VALIDITY_DAYS: u32 = 10 * 365;

/// An RSA 2048 self-signed certificate and its matching private key.
///
/// The key material stays in memory for the process lifetime; the type is
/// deliberately not `Clone` so a second copy cannot be made by accident.
#[derive(Debug)]
pub struct RsaIdentity {
    certificate: X509,
    private_key: PKey<Private>,
}

impl RsaIdentity {
    /// Mint a fresh RSA 2048 self-signed certificate with `CN=New World`.
    ///
    /// # Errors
    ///
    /// Returns [`CertError`] if OpenSSL cannot generate the key or build or
    /// sign the certificate.
    pub fn generate() -> Result<Self, CertError> {
        let private_key = PKey::from_rsa(Rsa::generate(RSA_BITS)?)?;

        let name = {
            let mut builder = X509NameBuilder::new()?;
            builder.append_entry_by_nid(Nid::COMMONNAME, COMMON_NAME)?;
            builder.build()
        };

        let serial = serial_number_from_now()?;
        let not_before = Asn1Time::days_from_now(0)?;
        let not_after = Asn1Time::days_from_now(VALIDITY_DAYS)?;

        let mut builder = X509Builder::new()?;
        builder.set_version(2)?;
        builder.set_serial_number(&serial)?;
        builder.set_subject_name(&name)?;
        builder.set_issuer_name(&name)?;
        builder.set_pubkey(&private_key)?;
        builder.set_not_before(&not_before)?;
        builder.set_not_after(&not_after)?;
        builder.sign(&private_key, MessageDigest::sha256())?;

        Ok(Self {
            certificate: builder.build(),
            private_key,
        })
    }

    /// The certificate to present to the peer.
    pub fn certificate(&self) -> &X509Ref {
        &self.certificate
    }

    /// The private key matching [`Self::certificate`].
    pub fn private_key(&self) -> &PKeyRef<Private> {
        &self.private_key
    }
}

/// Serial number from the current unix time, as `make_self_signed_cert` does.
fn serial_number_from_now() -> Result<Asn1Integer, CertError> {
    let seconds = time::OffsetDateTime::now_utc().unix_timestamp();
    let big = BigNum::from_dec_str(&seconds.to_string())?;
    Ok(Asn1Integer::from_bn(&big)?)
}

/// Error minting the server certificate.
#[derive(Debug)]
pub struct CertError(ErrorStack);

impl std::fmt::Display for CertError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "certificate generation failed: {}", self.0)
    }
}

impl std::error::Error for CertError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.0)
    }
}

impl From<ErrorStack> for CertError {
    fn from(error: ErrorStack) -> Self {
        Self(error)
    }
}
