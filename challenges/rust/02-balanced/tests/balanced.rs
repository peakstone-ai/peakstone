use challenge::is_balanced;

#[test]
fn empty_is_balanced() {
    assert!(is_balanced(""));
}

#[test]
fn simple_pairs() {
    assert!(is_balanced("()[]{}"));
    assert!(is_balanced("([{}])"));
}

#[test]
fn ignores_non_brackets() {
    assert!(is_balanced("(a + [b * c]) - {d}"));
    assert!(is_balanced("no brackets at all"));
}

#[test]
fn mismatched_type() {
    assert!(!is_balanced("(]"));
    assert!(!is_balanced("{)"));
}

#[test]
fn wrong_nesting_order() {
    assert!(!is_balanced("([)]"));
}

#[test]
fn unclosed_or_unopened() {
    assert!(!is_balanced("("));
    assert!(!is_balanced(")("));
    assert!(!is_balanced("(()"));
}
