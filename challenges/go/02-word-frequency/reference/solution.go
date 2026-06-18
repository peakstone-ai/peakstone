package challenge

import "strings"

// isAlphaNum reports whether b is an ASCII letter or digit.
func isAlphaNum(b byte) bool {
	return (b >= 'a' && b <= 'z') ||
		(b >= 'A' && b <= 'Z') ||
		(b >= '0' && b <= '9')
}

// WordFrequency counts occurrences of each word in text. Words are split on
// whitespace, have surrounding ASCII punctuation stripped, and are lowercased
// before counting. The returned map is always non-nil.
func WordFrequency(text string) map[string]int {
	freq := make(map[string]int)
	for _, tok := range strings.Fields(text) {
		word := strings.TrimFunc(tok, func(r rune) bool {
			return r < 128 && !isAlphaNum(byte(r))
		})
		if word == "" {
			continue
		}
		freq[strings.ToLower(word)]++
	}
	return freq
}
