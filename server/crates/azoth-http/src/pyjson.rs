//! Rendering JSON the way Python's `json.dumps` does.
//!
//! WHY THIS EXISTS
//! ===============
//! The plan's Phase 1 acceptance is that every route's body is **byte-identical** to the
//! prototype's for the same input. Python's `json.dumps` separates items with `", "` and keys from
//! values with `": "`; `serde_json` writes `","` and `":"`. The documents are semantically identical
//! and the client parses either — but "semantically identical" is exactly the standard that let two
//! ordering bugs through in `azoth-region`, so the bar here is bytes.
//!
//! With this formatter, a route can be compared against the prototype with `cmp` and a reviewer sees
//! a real difference instead of whitespace noise.
//!
//! WHAT IS NOT REPLICATED
//! ======================
//! Python's `ensure_ascii=True` default, which escapes non-ASCII as `\uXXXX`. The captured bodies
//! and every document we render are ASCII, and replicating the escaping would change the bytes for
//! any future non-ASCII content in a way that is easy to get subtly wrong (Python also emits
//! surrogate pairs for astral characters). If non-ASCII content ever enters a route, that decision
//! needs its own measurement rather than being inherited from here.

use serde_json::ser::Formatter;
use std::io;

/// A `serde_json` formatter that matches Python's default `json.dumps` separators.
#[derive(Debug, Default, Clone, Copy)]
pub struct PythonJson;

impl Formatter for PythonJson {
    /// `", "` between array items.
    fn begin_array_value<W: ?Sized + io::Write>(
        &mut self,
        writer: &mut W,
        first: bool,
    ) -> io::Result<()> {
        if first {
            Ok(())
        } else {
            writer.write_all(b", ")
        }
    }

    /// `", "` between object members.
    fn begin_object_key<W: ?Sized + io::Write>(
        &mut self,
        writer: &mut W,
        first: bool,
    ) -> io::Result<()> {
        if first {
            Ok(())
        } else {
            writer.write_all(b", ")
        }
    }

    /// `": "` between a key and its value.
    fn begin_object_value<W: ?Sized + io::Write>(&mut self, writer: &mut W) -> io::Result<()> {
        writer.write_all(b": ")
    }
}

/// Serialize a value the way Python's `json.dumps` would, with a trailing newline.
///
/// The newline matches the prototype, which serves `json.dumps(...) + "\n"`.
///
/// # Errors
/// A serialization failure, which for `Value` means a map with non-string keys.
pub fn to_python_bytes(value: &serde_json::Value) -> Result<Vec<u8>, serde_json::Error> {
    let mut out = Vec::new();
    let mut serializer = serde_json::Serializer::with_formatter(&mut out, PythonJson);
    serde::Serialize::serialize(value, &mut serializer)?;
    out.push(b'\n');
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn matches_python_separators() {
        let value = json!({"a": 1, "b": [1, 2], "c": {"d": "e"}});
        let bytes = to_python_bytes(&value).expect("serializes");
        let text = String::from_utf8(bytes).expect("utf8");
        assert_eq!(text, "{\"a\": 1, \"b\": [1, 2], \"c\": {\"d\": \"e\"}}\n");
    }

    #[test]
    fn an_empty_object_and_array_have_no_separators() {
        assert_eq!(
            String::from_utf8(to_python_bytes(&json!({})).expect("ok")).expect("utf8"),
            "{}\n"
        );
        assert_eq!(
            String::from_utf8(to_python_bytes(&json!([])).expect("ok")).expect("utf8"),
            "[]\n"
        );
    }

    #[test]
    fn a_single_item_gets_no_trailing_separator() {
        assert_eq!(
            String::from_utf8(to_python_bytes(&json!([1])).expect("ok")).expect("utf8"),
            "[1]\n"
        );
        assert_eq!(
            String::from_utf8(to_python_bytes(&json!({"k": "v"})).expect("ok")).expect("utf8"),
            "{\"k\": \"v\"}\n"
        );
    }

    #[test]
    fn key_order_is_preserved() {
        // serde_json's preserve_order feature is what makes this hold; without it the map would be
        // sorted and every rendered document would be alphabetised.
        let value: serde_json::Value =
            serde_json::from_str(r#"{"z":1,"a":2,"m":3}"#).expect("parses");
        let text = String::from_utf8(to_python_bytes(&value).expect("ok")).expect("utf8");
        assert_eq!(text, "{\"z\": 1, \"a\": 2, \"m\": 3}\n");
    }

    #[test]
    fn strings_containing_separators_are_not_mangled() {
        // A naive string-replace of `":"` with `": "` would corrupt this value; a formatter cannot.
        let value = json!({"k": "a:b, c"});
        let text = String::from_utf8(to_python_bytes(&value).expect("ok")).expect("utf8");
        assert_eq!(text, "{\"k\": \"a:b, c\"}\n");
    }

    #[test]
    fn a_trailing_newline_is_always_added() {
        for value in [json!(null), json!(true), json!(1), json!("s")] {
            let bytes = to_python_bytes(&value).expect("ok");
            assert_eq!(bytes.last(), Some(&b'\n'));
        }
    }
}
