use challenge::IntervalMap;

#[test]
fn point_lookup_respects_half_open_bounds() {
    let mut m = IntervalMap::new();
    m.insert(0, 10, "a");
    assert_eq!(m.get(5), Some(&"a"));
    assert_eq!(m.get(0), Some(&"a")); // start is inclusive
    assert_eq!(m.get(10), None); // end is exclusive
    assert_eq!(m.get(-1), None);
}

#[test]
fn empty_map_returns_none() {
    let m: IntervalMap<i32> = IntervalMap::new();
    assert_eq!(m.get(0), None);
    assert_eq!(m.get_all(0), Vec::<&i32>::new());
}

#[test]
fn newest_insert_wins_on_overlap() {
    let mut m = IntervalMap::new();
    m.insert(0, 10, 1);
    m.insert(5, 15, 2);
    assert_eq!(m.get(2), Some(&1)); // only the first interval
    assert_eq!(m.get(7), Some(&2)); // overlap -> newest wins
    assert_eq!(m.get(12), Some(&2)); // only the second interval
}

#[test]
fn get_all_returns_all_covering_newest_first() {
    let mut m = IntervalMap::new();
    m.insert(0, 10, 1);
    m.insert(5, 15, 2);
    m.insert(6, 8, 3);
    assert_eq!(m.get_all(7), vec![&3, &2, &1]);
    assert_eq!(m.get_all(2), vec![&1]);
    assert_eq!(m.get_all(20), Vec::<&i32>::new());
}

#[test]
fn empty_or_reversed_ranges_are_ignored() {
    let mut m = IntervalMap::new();
    m.insert(5, 5, "empty");
    m.insert(8, 3, "reversed");
    assert_eq!(m.get(5), None);
    assert_eq!(m.get(4), None);
}

#[test]
fn works_with_owned_string_values() {
    let mut m = IntervalMap::new();
    m.insert(0, 100, String::from("x"));
    assert_eq!(m.get(50), Some(&String::from("x")));
}
