pub fn group_consecutive<T: PartialEq + Clone>(items: &[T]) -> Vec<(T, usize)> {
    let mut out: Vec<(T, usize)> = Vec::new();
    for item in items {
        match out.last_mut() {
            Some((value, count)) if value == item => *count += 1,
            _ => out.push((item.clone(), 1)),
        }
    }
    out
}
