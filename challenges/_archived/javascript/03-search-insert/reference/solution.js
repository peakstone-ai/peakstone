export function searchInsert(sortedNums, target) {
  let lo = 0;
  let hi = sortedNums.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (sortedNums[mid] === target) {
      return mid;
    } else if (sortedNums[mid] < target) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  return lo;
}
