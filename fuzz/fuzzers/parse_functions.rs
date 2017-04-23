#![no_main]
#[macro_use] extern crate libfuzzer_sys;

extern crate cton_reader;
use cton_reader::parse_functions;

fuzz_target!(|data: &[u8]| {
    if let Ok(s) = String::from_utf8(data.to_vec()) {
        let _ = parse_functions(&s);
    }
});
