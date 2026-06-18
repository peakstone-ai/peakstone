pub fn eval_rpn(tokens: &[&str]) -> Result<f64, String> {
    let mut stack: Vec<f64> = Vec::new();
    for &tok in tokens {
        match tok {
            "+" | "-" | "*" | "/" => {
                let b = stack
                    .pop()
                    .ok_or_else(|| format!("too few operands for '{tok}'"))?;
                let a = stack
                    .pop()
                    .ok_or_else(|| format!("too few operands for '{tok}'"))?;
                let r = match tok {
                    "+" => a + b,
                    "-" => a - b,
                    "*" => a * b,
                    "/" => {
                        if b == 0.0 {
                            return Err("division by zero".to_string());
                        }
                        a / b
                    }
                    _ => unreachable!(),
                };
                stack.push(r);
            }
            other => match other.parse::<f64>() {
                Ok(n) => stack.push(n),
                Err(_) => return Err(format!("unknown token: '{other}'")),
            },
        }
    }
    match stack.len() {
        1 => Ok(stack[0]),
        0 => Err("empty expression".to_string()),
        n => Err(format!("leftover operands: {n} values remain")),
    }
}
