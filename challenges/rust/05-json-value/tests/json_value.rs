use challenge::{parse, Value};

#[test]
fn parses_primitives() {
    assert_eq!(parse("null"), Ok(Value::Null));
    assert_eq!(parse("true"), Ok(Value::Bool(true)));
    assert_eq!(parse("false"), Ok(Value::Bool(false)));
    assert_eq!(parse("42"), Ok(Value::Number(42.0)));
    assert_eq!(parse("-3.5"), Ok(Value::Number(-3.5)));
    assert_eq!(parse("1e3"), Ok(Value::Number(1000.0)));
    assert_eq!(parse("\"hi\""), Ok(Value::Str("hi".to_string())));
}

#[test]
fn ignores_surrounding_whitespace() {
    assert_eq!(parse("  \n true \t "), Ok(Value::Bool(true)));
}

#[test]
fn parses_string_escapes() {
    assert_eq!(parse("\"a\\nb\""), Ok(Value::Str("a\nb".to_string())));
    assert_eq!(parse("\"q\\\"q\""), Ok(Value::Str("q\"q".to_string())));
}

#[test]
fn parses_empty_array_and_object() {
    assert_eq!(parse("[]"), Ok(Value::Array(vec![])));
    assert_eq!(parse("{}"), Ok(Value::Object(vec![])));
}

#[test]
fn parses_nested_structures() {
    let parsed = parse("{\"a\": [1, 2], \"b\": {\"c\": true}}").unwrap();
    let expected = Value::Object(vec![
        ("a".to_string(), Value::Array(vec![Value::Number(1.0), Value::Number(2.0)])),
        ("b".to_string(), Value::Object(vec![("c".to_string(), Value::Bool(true))])),
    ]);
    assert_eq!(parsed, expected);
}

#[test]
fn preserves_object_member_order() {
    let parsed = parse("{\"z\": 1, \"a\": 2}").unwrap();
    let expected = Value::Object(vec![
        ("z".to_string(), Value::Number(1.0)),
        ("a".to_string(), Value::Number(2.0)),
    ]);
    assert_eq!(parsed, expected);
}

#[test]
fn rejects_trailing_characters() {
    assert!(parse("null null").is_err());
    assert!(parse("[1, 2] x").is_err());
}

#[test]
fn rejects_malformed_input() {
    assert!(parse("").is_err());
    assert!(parse("[1, 2").is_err());
    assert!(parse("{\"a\": }").is_err());
    assert!(parse("\"unterminated").is_err());
    assert!(parse("{\"a\" 1}").is_err());
}
