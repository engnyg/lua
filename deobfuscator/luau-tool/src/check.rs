use serde_json::json;

pub fn run(src: &str) -> String {
    let result = full_moon::parse_fallible(src, full_moon::LuaVersion::luau());
    let errors: Vec<_> = result
        .errors()
        .iter()
        .map(|e| json!({"line": e.range().0.line(), "message": e.error_message()}))
        .collect();
    json!({ "errors": errors }).to_string()
}
