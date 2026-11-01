//! ECDSA P-256 self-signed certificate for the DTLS spike.
//!
//! dimpl ships a certificate generator, but it lives behind the `rcgen`
//! feature, which enables `aws-lc-rs` -- the C library this spike exists to
//! avoid. So the certificate is minted here with `p256` and `x509-cert`, both
//! pure Rust.
//!
//! # Provenance
//!
//! The certificate is generated **fresh in memory at process start**, not read
//! from disk. `self_signed_p256` draws a P-256 key from the OS RNG, builds a
//! one-year v3 self-signed certificate around the matching public key, and
//! returns dimpl's [`DtlsCertificate`] (DER certificate + PKCS#8 DER private
//! key). Nothing is persisted, so no private key is ever committed or logged.
//!
//! The same function mints the certificate for the loopback client in the
//! `handshake` test; each side gets its own key.

use std::str::FromStr;
use std::time::Duration;

use dimpl::DtlsCertificate;
use p256::ecdsa::SigningKey;
use p256::elliptic_curve::Generate;
use p256::pkcs8::EncodePrivateKey;
use x509_cert::builder::profile::BuilderProfile;
use x509_cert::builder::{Builder, CertificateBuilder};
use x509_cert::certificate::TbsCertificate;
use x509_cert::der::Encode;
use x509_cert::ext::pkix::BasicConstraints;
use x509_cert::ext::{Extension, ToExtension};
use x509_cert::name::Name;
use x509_cert::serial_number::SerialNumber;
use x509_cert::spki::{SubjectPublicKeyInfo, SubjectPublicKeyInfoRef};
use x509_cert::time::Validity;

/// Subject distinguished name of the spike certificate.
const SUBJECT: &str = "CN=Everfall DTLS Spike";

/// Serial number of the spike certificate. One certificate per process, so a
/// constant serial keeps the DER stable across runs for diffing.
const SERIAL: u32 = 1;

/// The certificate is valid for one year from mint time.
const VALIDITY: Duration = Duration::from_hours(365 * 24);

/// Error minting the spike certificate.
#[derive(Debug)]
pub struct CertError(Box<dyn std::error::Error + Send + Sync + 'static>);

impl CertError {
    fn new<E: std::error::Error + Send + Sync + 'static>(error: E) -> Self {
        Self(Box::new(error))
    }
}

impl std::fmt::Display for CertError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "certificate generation failed: {}", self.0)
    }
}

impl std::error::Error for CertError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(self.0.as_ref())
    }
}

/// A self-signed end-entity profile: issuer == subject, one `BasicConstraints`
/// extension.
#[derive(Debug, Clone)]
struct SpikeProfile {
    name: Name,
}

impl BuilderProfile for SpikeProfile {
    fn get_issuer(&self, _subject: &Name) -> Name {
        self.name.clone()
    }

    fn get_subject(&self) -> Name {
        self.name.clone()
    }

    fn build_extensions(
        &self,
        _spk: SubjectPublicKeyInfoRef<'_>,
        _issuer_spk: SubjectPublicKeyInfoRef<'_>,
        _tbs: &TbsCertificate,
    ) -> x509_cert::builder::Result<Vec<Extension>> {
        // A single extension keeps the certificate v3 and tells any validating
        // stack that this is explicitly a non-CA end-entity certificate.
        let basic = BasicConstraints {
            ca: false,
            path_len_constraint: None,
        };
        let extension = (&basic).to_extension(&self.name, &[])?;
        Ok(vec![extension])
    }
}

/// Mint a fresh ECDSA P-256 self-signed certificate and matching private key.
///
/// # Errors
///
/// Returns [`CertError`] if the subject name, public key or validity cannot be
/// encoded, or if the certificate or private key cannot be serialized.
pub fn self_signed_p256() -> Result<DtlsCertificate, CertError> {
    let mut rng = rand::rng();
    let signing_key = SigningKey::generate_from_rng(&mut rng);

    let name = Name::from_str(SUBJECT).map_err(CertError::new)?;
    let spki =
        SubjectPublicKeyInfo::from_key(signing_key.verifying_key()).map_err(CertError::new)?;
    let validity = Validity::from_now(VALIDITY).map_err(CertError::new)?;

    let builder = CertificateBuilder::new(
        SpikeProfile { name },
        SerialNumber::from(SERIAL),
        validity,
        spki,
    )
    .map_err(CertError::new)?;

    // ECDSA has more than one `Signer` impl, so the signature type is named
    // explicitly, as x509-cert's own example requires.
    let certificate = builder
        .build::<_, ecdsa::der::Signature<p256::NistP256>>(&signing_key)
        .map_err(CertError::new)?
        .to_der()
        .map_err(CertError::new)?;

    let private_key = signing_key
        .to_pkcs8_der()
        .map_err(CertError::new)?
        .as_bytes()
        .to_vec();

    Ok(DtlsCertificate {
        certificate,
        private_key,
    })
}
