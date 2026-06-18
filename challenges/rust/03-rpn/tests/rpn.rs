use challenge::eval_rpn;

#[test]
fn basic_eval() {
    assert_eq!(eval_rpn(&["2", "3", "+"]), Ok(5.0));
    assert_eq!(eval_rpn(&["8", "2", "/"]), Ok(4.0));
    assert_eq!(eval_rpn(&["42"]), Ok(42.0));
}

#[test]
fn operator_order_matters() {
    assert_eq!(eval_rpn(&["3", "4", "-"]), Ok(-1.0));
    assert_eq!(eval_rpn(&["10", "4", "-"]), Ok(6.0));
}

#[test]
fn precedence_via_rpn() {
    // (1 + 2) * 4 + 5 - 3  =  14
    assert_eq!(
        eval_rpn(&["5", "1", "2", "+", "4", "*", "+", "3", "-"]),
        Ok(14.0)
    );
}

#[test]
fn err_too_few_operands() {
    assert!(eval_rpn(&["1", "+"]).is_err());
    assert!(eval_rpn(&["+"]).is_err());
}

#[test]
fn err_leftover_operands() {
    assert!(eval_rpn(&["1", "2"]).is_err());
    assert!(eval_rpn(&["1", "2", "3", "+"]).is_err());
}

#[test]
fn err_empty_input() {
    assert!(eval_rpn(&[]).is_err());
}

#[test]
fn err_unknown_token() {
    assert!(eval_rpn(&["1", "foo", "+"]).is_err());
    assert!(eval_rpn(&["1", "2", "%"]).is_err());
}

#[test]
fn err_division_by_zero() {
    assert!(eval_rpn(&["1", "0", "/"]).is_err());
}
