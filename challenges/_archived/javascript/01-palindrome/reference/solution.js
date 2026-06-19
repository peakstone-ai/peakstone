export function isPalindrome(s) {
  const cleaned = String(s).toLowerCase().replace(/[^a-z0-9]/g, "");
  let i = 0, j = cleaned.length - 1;
  while (i < j) {
    if (cleaned[i] !== cleaned[j]) return false;
    i++; j--;
  }
  return true;
}
