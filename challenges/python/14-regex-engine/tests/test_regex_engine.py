from solution import fullmatch


def test_empty_pattern_matches_only_empty():
    assert fullmatch("", "") is True
    assert fullmatch("", "x") is False
    assert fullmatch("", "abc") is False


def test_plain_literals():
    assert fullmatch("abc", "abc") is True
    assert fullmatch("abc", "abd") is False
    assert fullmatch("a", "a") is True
    assert fullmatch("a", "") is False


def test_anchoring_requires_full_consume():
    # leading and trailing extra chars must cause failure
    assert fullmatch("a", "ab") is False
    assert fullmatch("b", "ab") is False
    assert fullmatch("ab", "abc") is False
    assert fullmatch("bc", "abc") is False
    assert fullmatch("abc", "ab") is False


def test_dot_matches_any_single_char():
    assert fullmatch("h.t", "hat") is True
    assert fullmatch("h.t", "h9t") is True
    assert fullmatch(".", "x") is True
    assert fullmatch(".", "") is False     # needs exactly one char
    assert fullmatch("a.c", "ac") is False  # dot must consume one
    assert fullmatch("...", "abc") is True
    assert fullmatch("...", "ab") is False


def test_star_zero_or_more():
    assert fullmatch("a*", "") is True
    assert fullmatch("a*", "a") is True
    assert fullmatch("a*", "aaaa") is True
    assert fullmatch("a*", "aaab") is False
    assert fullmatch("ba*", "b") is True
    assert fullmatch("ba*c", "bc") is True
    assert fullmatch("ba*c", "baaac") is True


def test_plus_one_or_more():
    assert fullmatch("a+", "") is False
    assert fullmatch("a+", "a") is True
    assert fullmatch("a+", "aaa") is True
    assert fullmatch("a+", "aaab") is False
    assert fullmatch("ba+c", "bac") is True
    assert fullmatch("ba+c", "bc") is False


def test_question_zero_or_one():
    assert fullmatch("a?", "") is True
    assert fullmatch("a?", "a") is True
    assert fullmatch("a?", "aa") is False
    assert fullmatch("colou?r", "color") is True
    assert fullmatch("colou?r", "colour") is True
    assert fullmatch("colou?r", "colouur") is False
    assert fullmatch("a?b", "b") is True
    assert fullmatch("a?b", "ab") is True


def test_greedy_backtracking_star():
    # '*' must give characters back so the trailing 'a' can match
    assert fullmatch("a*a", "aaa") is True
    assert fullmatch("a*a", "a") is True
    assert fullmatch("a*a", "") is False     # need at least one 'a'
    assert fullmatch("a*ab", "aaab") is True
    assert fullmatch("a*ab", "ab") is True


def test_dotstar_matches_anything():
    assert fullmatch(".*", "") is True
    assert fullmatch(".*", "anything at all 123 !@#") is True
    assert fullmatch(".+", "") is False
    assert fullmatch(".+", "x") is True
    # backtracking through dot-star
    assert fullmatch(".*b", "aaabxb") is True
    assert fullmatch(".*b", "aaabx") is False


def test_dotstar_backtracking_with_suffix():
    assert fullmatch("a.*z", "az") is True
    assert fullmatch("a.*z", "abcz") is True
    assert fullmatch("a.*z", "abc") is False
    assert fullmatch("x.*y.*z", "xyz") is True
    assert fullmatch("x.*y.*z", "x111y222z") is True


def test_char_class_basic():
    assert fullmatch("[abc]", "a") is True
    assert fullmatch("[abc]", "b") is True
    assert fullmatch("[abc]", "c") is True
    assert fullmatch("[abc]", "d") is False
    assert fullmatch("[abc]", "") is False
    assert fullmatch("[abc]", "ab") is False  # class matches exactly one


def test_char_class_ranges():
    assert fullmatch("[a-z]", "m") is True
    assert fullmatch("[a-z]", "M") is False
    assert fullmatch("[0-9]", "7") is True
    assert fullmatch("[0-9]", "a") is False
    assert fullmatch("[A-Za-z0-9]", "Q") is True
    assert fullmatch("[A-Za-z0-9]", "q") is True
    assert fullmatch("[A-Za-z0-9]", "5") is True
    assert fullmatch("[A-Za-z0-9]", "_") is False


def test_char_class_with_quantifiers():
    assert fullmatch("[a-z]+", "hello") is True
    assert fullmatch("[a-z]+", "Hello") is False
    assert fullmatch("[a-z]+[0-9]*", "abc12") is True
    assert fullmatch("[a-z]+[0-9]*", "abc") is True
    assert fullmatch("[a-z]+[0-9]*", "123") is False
    assert fullmatch("[0-9]*", "") is True


def test_negated_char_class():
    assert fullmatch("[^0-9]", "a") is True
    assert fullmatch("[^0-9]", "5") is False
    assert fullmatch("[^0-9]+", "abc") is True
    assert fullmatch("[^0-9]+", "ab3c") is False
    assert fullmatch("[^abc]", "d") is True
    assert fullmatch("[^abc]", "a") is False


def test_literal_dash_in_class():
    # '-' first or last in the class is a literal dash
    assert fullmatch("[-a]", "-") is True
    assert fullmatch("[-a]", "a") is True
    assert fullmatch("[a-]", "-") is True
    assert fullmatch("[a-]", "a") is True
    assert fullmatch("[a-]", "b") is False
    # literal dash in a negated class
    assert fullmatch("[^-]", "-") is False
    assert fullmatch("[^-]", "x") is True


def test_escaped_metacharacters():
    assert fullmatch("h\\.t", "h.t") is True
    assert fullmatch("h\\.t", "hat") is False   # escaped dot is literal
    assert fullmatch("a\\*b", "a*b") is True
    assert fullmatch("a\\*b", "aab") is False
    assert fullmatch("a\\\\b", "a\\b") is True   # \\ -> literal backslash
    assert fullmatch("\\[x\\]", "[x]") is True
    assert fullmatch("a\\+", "a+") is True
    assert fullmatch("a\\?", "a?") is True


def test_escaped_element_with_quantifier():
    # quantifier applies to the escaped element
    assert fullmatch("\\.*", "") is True
    assert fullmatch("\\.*", "...") is True
    assert fullmatch("\\.*", ".a.") is False
    assert fullmatch("\\*+", "***") is True
    assert fullmatch("\\*+", "") is False


def test_combined_realistic_patterns():
    # identifier-ish: letter then letters/digits/underscore-via-class
    assert fullmatch("[a-z][a-z0-9]*", "x") is True
    assert fullmatch("[a-z][a-z0-9]*", "var123") is True
    assert fullmatch("[a-z][a-z0-9]*", "1var") is False
    # crude decimal: digits . digits
    assert fullmatch("[0-9]+\\.[0-9]+", "3.14") is True
    assert fullmatch("[0-9]+\\.[0-9]+", "3.") is False
    assert fullmatch("[0-9]+\\.[0-9]+", ".14") is False
    assert fullmatch("[0-9]+\\.[0-9]+", "10.005") is True


def test_clear_non_matches():
    assert fullmatch("abc", "") is False
    assert fullmatch("a+b+", "aaa") is False
    assert fullmatch("[xyz]+", "xya") is False
    assert fullmatch("a.c.e", "abcd") is False
    assert fullmatch("a*b*c*", "cba") is False
