//! Timestamp formatting for the client's JSON.
//!
//! WHY THIS IS HAND-ROLLED
//! =======================
//! Every date the client parses from these routes is the same format — `YYYY-MM-DDTHH:MM:SSZ`, UTC —
//! and there are thirty-two of them in one character record. A date library would be a dependency
//! for eight `format!` fields. The algorithm is Howard Hinnant's `civil_from_days`, which is exact
//! for every proleptic Gregorian date, so the absence of a library costs correctness nothing.
//!
//! The client's own parser is the reason the trailing `Z` and the missing fractional seconds matter:
//! `createdDate` and friends are compared and displayed, and a shape it does not recognise is a
//! character panel with blank dates rather than an error.

/// A timestamp as the wire spells it: `YYYY-MM-DDTHH:MM:SSZ`, UTC.
///
/// Hand-rolled for the same reason the generator is: the only formatting needed is this one, and a
/// date library would be a dependency for eight `format!` fields. The algorithm is Howard Hinnant's
/// `civil_from_days`, which is exact for every proleptic Gregorian date.
#[must_use]
pub fn iso8601_utc(seconds: i64) -> String {
    let days = seconds.div_euclid(86_400);
    let of_day = seconds.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        of_day / 3_600,
        (of_day % 3_600) / 60,
        of_day % 60
    )
}

/// Days since 1970-01-01 to a proleptic Gregorian `(year, month, day)`.
fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let day_of_era = z - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_position = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_position + 2) / 5 + 1;
    let month = if month_position < 10 {
        month_position + 3
    } else {
        month_position - 9
    };
    (if month <= 2 { year + 1 } else { year }, month, day)
}

