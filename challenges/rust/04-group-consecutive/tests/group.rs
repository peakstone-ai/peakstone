use challenge::group_consecutive;

#[test]
fn ints_with_runs() {
    assert_eq!(
        group_consecutive(&[1, 1, 2, 3, 3, 3]),
        vec![(1, 2), (2, 1), (3, 3)]
    );
}

#[test]
fn chars_prove_generic() {
    assert_eq!(
        group_consecutive(&['a', 'a', 'b', 'a']),
        vec![('a', 2), ('b', 1), ('a', 1)]
    );
}

#[test]
fn works_for_owned_strings() {
    let v = vec!["x".to_string(), "x".to_string(), "y".to_string()];
    assert_eq!(
        group_consecutive(&v),
        vec![("x".to_string(), 2), ("y".to_string(), 1)]
    );
}

#[test]
fn empty_input() {
    let out = group_consecutive::<i32>(&[]);
    assert_eq!(out, Vec::<(i32, usize)>::new());
}

#[test]
fn all_distinct() {
    assert_eq!(
        group_consecutive(&[1, 2, 3]),
        vec![(1, 1), (2, 1), (3, 1)]
    );
}

#[test]
fn all_same() {
    assert_eq!(group_consecutive(&[7, 7, 7]), vec![(7, 3)]);
}

#[test]
fn single_element() {
    assert_eq!(group_consecutive(&[42]), vec![(42, 1)]);
}
