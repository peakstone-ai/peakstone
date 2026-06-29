pub struct IntervalMap<T> {
    intervals: Vec<(i64, i64, T)>,
}

impl<T> IntervalMap<T> {
    pub fn new() -> Self {
        IntervalMap { intervals: Vec::new() }
    }

    pub fn insert(&mut self, start: i64, end: i64, value: T) {
        if start < end {
            self.intervals.push((start, end, value));
        }
    }

    pub fn get(&self, point: i64) -> Option<&T> {
        self.intervals
            .iter()
            .rev()
            .find(|(s, e, _)| *s <= point && point < *e)
            .map(|(_, _, v)| v)
    }

    pub fn get_all(&self, point: i64) -> Vec<&T> {
        self.intervals
            .iter()
            .rev()
            .filter(|(s, e, _)| *s <= point && point < *e)
            .map(|(_, _, v)| v)
            .collect()
    }
}

impl<T> Default for IntervalMap<T> {
    fn default() -> Self {
        Self::new()
    }
}
