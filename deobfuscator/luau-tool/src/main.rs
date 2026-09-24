mod check;
mod predicates;
mod resolve;

use std::{env, fs, process, thread};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("usage: luau-tool <check|predicates|resolve> <file.lua>");
        process::exit(2);
    }
    let (cmd, path) = (args[1].clone(), args[2].clone());
    let src = fs::read_to_string(&path).expect("input must be UTF-8");

    // deeply nested decompiled code overflows the default 8 MB stack
    let out = thread::Builder::new()
        .stack_size(1 << 30)
        .spawn(move || match cmd.as_str() {
            "check" => check::run(&src),
            "predicates" => predicates::run(&src),
            "resolve" => resolve::run(&src),
            other => {
                eprintln!("unknown command {other}");
                process::exit(2);
            }
        })
        .unwrap()
        .join()
        .unwrap();
    println!("{out}");
}
