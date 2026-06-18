use challenge::run_length_encode;

#[test]
fn basic_runs() {
    assert_eq!(run_length_encode("aaabbc"), "a3b2c1");
}

#[test]
fn empty() {
    assert_eq!(run_length_encode(""), "");
}

#[test]
fn all_singles() {
    assert_eq!(run_length_encode("abc"), "a1b1c1");
}
