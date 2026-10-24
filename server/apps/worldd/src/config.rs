//! Configuration, validated at startup.
//!
//! WHY THERE ARE NO ENVIRONMENT VARIABLES
//! =====================================
//! The Python prototype is configured by roughly forty `AZOTH_*` variables, and `STATUS.md` records
//! what that costs: three of them had to be exported in the same shell that started the service, a
//! missing one was **not an error**, and the result was "a silently different experiment" that cost
//! an afternoon. A setting that can be absent without anyone noticing is not configuration.
//!
//! So this binary reads its settings from arguments with defaults, fails loudly on a missing
//! required file, and has no `std::env::var` anywhere.

use std::net::SocketAddr;
use std::path::PathBuf;

/// The world's runtime configuration.
#[derive(Debug, Clone, PartialEq)]
pub struct Config {
    /// The UDP address to bind. The prototype uses `127.0.0.1:9000`, which is what the queue
    /// ticket's `RepAddress` points at.
    pub bind: SocketAddr,
    /// Where the DTLS certificate lives. Generated on first start if absent.
    pub cert_dir: PathBuf,
    /// The simulation rate. The capture measured the official server at 50 Hz and the client's own
    /// input cadence at 20 Hz, so these are not the same clock.
    pub tick_hz: f64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            bind: "127.0.0.1:9000".parse().expect("a literal address parses"),
            cert_dir: PathBuf::from("private-client/runtime/certs"),
            tick_hz: 50.0,
        }
    }
}

impl Config {
    /// Parse `--bind`, `--cert-dir` and `--tick-hz`.
    ///
    /// Hand-rolled: three flags with defaults do not justify a CLI dependency, and writing the
    /// errors for these three is more useful than a framework's generic message.
    ///
    /// # Errors
    /// A message naming the flag when a value is missing or unparseable.
    pub fn from_args<I: IntoIterator<Item = String>>(args: I) -> Result<Self, String> {
        let mut config = Self::default();
        let mut iter = args.into_iter();
        while let Some(arg) = iter.next() {
            match arg.as_str() {
                "--bind" => {
                    let value = iter.next().ok_or("--bind needs a value")?;
                    config.bind = value
                        .parse()
                        .map_err(|_| format!("--bind {value:?} is not an address"))?;
                }
                "--cert-dir" => {
                    config.cert_dir = PathBuf::from(iter.next().ok_or("--cert-dir needs a value")?);
                }
                "--tick-hz" => {
                    let value = iter.next().ok_or("--tick-hz needs a value")?;
                    let hz: f64 = value
                        .parse()
                        .map_err(|_| format!("--tick-hz {value:?} is not a number"))?;
                    if !(1.0..=1000.0).contains(&hz) {
                        return Err(format!("--tick-hz {hz} is outside 1..=1000"));
                    }
                    config.tick_hz = hz;
                }
                "--help" | "-h" => return Err(Self::usage()),
                other => return Err(format!("unknown argument {other:?}\n\n{}", Self::usage())),
            }
        }
        Ok(config)
    }

    /// The usage text.
    #[must_use]
    pub fn usage() -> String {
        "usage: worldd [--bind ADDR] [--cert-dir DIR] [--tick-hz HZ]".to_string()
    }

    /// The tick interval this configuration implies.
    #[must_use]
    pub fn tick_interval(&self) -> std::time::Duration {
        std::time::Duration::from_secs_f64(1.0 / self.tick_hz)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_defaults_match_the_prototype() {
        let config = Config::default();
        assert_eq!(config.bind.port(), 9000, "the ticket's RepAddress points here");
        assert!((config.tick_hz - 50.0).abs() < f64::EPSILON, "the measured rate");
    }

    #[test]
    fn fifty_hertz_is_a_twenty_millisecond_budget() {
        let config = Config::default();
        assert_eq!(config.tick_interval(), std::time::Duration::from_millis(20));
    }

    #[test]
    fn parses_every_flag() {
        let config = Config::from_args(
            ["--bind", "0.0.0.0:9100", "--cert-dir", "/tmp/c", "--tick-hz", "30"]
                .into_iter()
                .map(String::from),
        )
        .expect("parses");
        assert_eq!(config.bind.port(), 9100);
        assert_eq!(config.cert_dir, PathBuf::from("/tmp/c"));
        assert!((config.tick_hz - 30.0).abs() < f64::EPSILON);
    }

    #[test]
    fn a_missing_value_is_an_error_not_a_default() {
        let err = Config::from_args(["--bind"].into_iter().map(String::from)).expect_err("fails");
        assert!(err.contains("--bind"), "{err}");
    }

    #[test]
    fn a_bad_address_is_an_error() {
        let err = Config::from_args(["--bind", "not-an-address"].into_iter().map(String::from))
            .expect_err("fails");
        assert!(err.contains("not-an-address"), "{err}");
    }

    #[test]
    fn an_out_of_range_tick_rate_is_an_error() {
        // A rate outside this range is either a typo or a measurement nobody took.
        for bad in ["0", "0.5", "5000"] {
            let err = Config::from_args(["--tick-hz", bad].into_iter().map(String::from))
                .expect_err(bad);
            assert!(err.contains("--tick-hz"), "{bad}: {err}");
        }
    }

    #[test]
    fn no_arguments_gives_the_defaults() {
        assert_eq!(
            Config::from_args(std::iter::empty()).expect("parses"),
            Config::default()
        );
    }
}
