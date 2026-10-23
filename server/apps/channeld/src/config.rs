//! Configuration, validated at startup.
//!
//! WHY THIS IS ONE STRUCT AND NOT ENVIRONMENT LOOKUPS
//! ==================================================
//! The Python prototype's failure mode is recorded in `STATUS.md` (2026-10-22): three `AZOTH_*`
//! environment variables had to be exported in the same shell that started the service, a missing
//! one was **not an error**, and the result was "a silently different experiment" that cost an
//! afternoon. A setting that can be absent without anyone noticing is not configuration.
//!
//! So: every path is a field, every field has a default, and a missing *required* file is a startup
//! error with the path in the message. Nothing is read from the environment.

use std::path::{Path, PathBuf};

/// The gateway's runtime configuration.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Config {
    /// Bind host.
    pub host: String,
    /// Bind port. The prototype serves 8080 behind Caddy on 443.
    pub port: u16,
    /// Where the checked-in seed data lives: `channel-azoth.json`, `worlds.json`.
    pub data_dir: PathBuf,
    /// Where the captured CMS bodies live: `cms_news.json`, `cms_tiles.json`.
    pub schemas_dir: PathBuf,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_string(),
            port: 8080,
            // Repo-relative defaults, resolved from the workspace root at runtime.
            data_dir: PathBuf::from("services/gateway/src/azoth_gateway/data"),
            schemas_dir: PathBuf::from("research/schemas/live"),
        }
    }
}

impl Config {
    /// Parse `--host`, `--port`, `--data-dir` and `--schemas-dir` from arguments.
    ///
    /// Hand-rolled rather than pulling a CLI framework: four flags with defaults do not justify a
    /// dependency, and the error messages are more useful when written for these four.
    ///
    /// # Errors
    /// A message naming the flag when a value is missing or unparseable.
    pub fn from_args<I: IntoIterator<Item = String>>(args: I) -> Result<Self, String> {
        let mut config = Self::default();
        let mut iter = args.into_iter();
        while let Some(arg) = iter.next() {
            match arg.as_str() {
                "--host" => {
                    config.host = iter.next().ok_or("--host needs a value")?;
                }
                "--port" => {
                    let value = iter.next().ok_or("--port needs a value")?;
                    config.port = value
                        .parse()
                        .map_err(|_| format!("--port {value:?} is not a number"))?;
                }
                "--data-dir" => {
                    config.data_dir = PathBuf::from(iter.next().ok_or("--data-dir needs a value")?);
                }
                "--schemas-dir" => {
                    config.schemas_dir =
                        PathBuf::from(iter.next().ok_or("--schemas-dir needs a value")?);
                }
                "--help" | "-h" => {
                    return Err(Self::usage());
                }
                other => return Err(format!("unknown argument {other:?}\n\n{}", Self::usage())),
            }
        }
        Ok(config)
    }

    /// The usage text.
    #[must_use]
    pub fn usage() -> String {
        "usage: channeld [--host H] [--port P] [--data-dir DIR] [--schemas-dir DIR]".to_string()
    }

    /// The channel seed document.
    #[must_use]
    pub fn channel_seed(&self) -> PathBuf {
        self.data_dir.join("channel-azoth.json")
    }

    /// The world/region registry seed.
    #[must_use]
    pub fn registry_seed(&self) -> PathBuf {
        self.data_dir.join("worlds.json")
    }

    /// The captured news body.
    #[must_use]
    pub fn cms_news(&self) -> PathBuf {
        self.schemas_dir.join("cms_news.json")
    }

    /// The captured marketing-tiles body.
    #[must_use]
    pub fn cms_tiles(&self) -> PathBuf {
        self.schemas_dir.join("cms_tiles.json")
    }

    /// Fail when a required file is absent, naming the path.
    ///
    /// # Errors
    /// The path and what it is for.
    pub fn require(&self, path: &Path, what: &str) -> Result<(), String> {
        if path.is_file() {
            Ok(())
        } else {
            Err(format!("{what} not found at {}", path.display()))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_defaults_match_the_prototype() {
        let config = Config::default();
        assert_eq!(config.host, "127.0.0.1");
        assert_eq!(config.port, 8080, "the prototype serves 8080 behind Caddy");
    }

    #[test]
    fn parses_every_flag() {
        let config = Config::from_args(
            [
                "--host",
                "0.0.0.0",
                "--port",
                "9001",
                "--data-dir",
                "/tmp/data",
                "--schemas-dir",
                "/tmp/schemas",
            ]
            .into_iter()
            .map(String::from),
        )
        .expect("parses");
        assert_eq!(config.host, "0.0.0.0");
        assert_eq!(config.port, 9001);
        assert_eq!(config.data_dir, PathBuf::from("/tmp/data"));
        assert_eq!(config.schemas_dir, PathBuf::from("/tmp/schemas"));
    }

    #[test]
    fn a_missing_value_is_an_error_not_a_default() {
        // The whole point of this module: a setting that can be absent without notice is not
        // configuration.
        let err = Config::from_args(["--port"].into_iter().map(String::from)).expect_err("fails");
        assert!(err.contains("--port"), "{err}");
    }

    #[test]
    fn a_bad_port_is_an_error() {
        let err = Config::from_args(["--port", "eighty"].into_iter().map(String::from))
            .expect_err("fails");
        assert!(err.contains("eighty"), "{err}");
    }

    #[test]
    fn an_unknown_flag_is_an_error_with_usage() {
        let err = Config::from_args(["--nope"].into_iter().map(String::from)).expect_err("fails");
        assert!(err.contains("--nope"), "{err}");
        assert!(err.contains("usage:"), "the message must say how to use it");
    }

    #[test]
    fn no_arguments_gives_the_defaults() {
        let config = Config::from_args(std::iter::empty()).expect("parses");
        assert_eq!(config, Config::default());
    }

    #[test]
    fn the_paths_are_built_from_the_directories() {
        let config = Config::default();
        assert!(config.channel_seed().ends_with("channel-azoth.json"));
        assert!(config.registry_seed().ends_with("worlds.json"));
        assert!(config.cms_news().ends_with("cms_news.json"));
        assert!(config.cms_tiles().ends_with("cms_tiles.json"));
    }

    #[test]
    fn require_names_the_missing_path() {
        let config = Config::default();
        let err = config
            .require(Path::new("/definitely/not/here.json"), "the registry seed")
            .expect_err("must fail");
        assert!(err.contains("the registry seed"), "{err}");
        assert!(err.contains("/definitely/not/here.json"), "{err}");
    }
}
