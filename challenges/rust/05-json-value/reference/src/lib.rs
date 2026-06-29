#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Number(f64),
    Str(String),
    Array(Vec<Value>),
    Object(Vec<(String, Value)>),
}

#[derive(Debug, Clone, PartialEq)]
pub struct ParseError {
    pub message: String,
    pub position: usize,
}

struct Parser {
    chars: Vec<char>,
    pos: usize,
}

impl Parser {
    fn err<T>(&self, msg: &str) -> Result<T, ParseError> {
        Err(ParseError { message: msg.to_string(), position: self.pos })
    }

    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    fn bump(&mut self) -> Option<char> {
        let c = self.peek();
        if c.is_some() {
            self.pos += 1;
        }
        c
    }

    fn skip_ws(&mut self) {
        while let Some(c) = self.peek() {
            if c == ' ' || c == '\t' || c == '\n' || c == '\r' {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    fn parse_value(&mut self) -> Result<Value, ParseError> {
        self.skip_ws();
        match self.peek() {
            Some('n') => self.parse_lit("null", Value::Null),
            Some('t') => self.parse_lit("true", Value::Bool(true)),
            Some('f') => self.parse_lit("false", Value::Bool(false)),
            Some('"') => Ok(Value::Str(self.parse_string()?)),
            Some('[') => self.parse_array(),
            Some('{') => self.parse_object(),
            Some(c) if c == '-' || c.is_ascii_digit() => self.parse_number(),
            _ => self.err("unexpected token"),
        }
    }

    fn parse_lit(&mut self, lit: &str, val: Value) -> Result<Value, ParseError> {
        for expected in lit.chars() {
            if self.bump() != Some(expected) {
                return self.err("invalid literal");
            }
        }
        Ok(val)
    }

    fn parse_string(&mut self) -> Result<String, ParseError> {
        self.bump(); // opening quote
        let mut s = String::new();
        loop {
            match self.bump() {
                None => return self.err("unterminated string"),
                Some('"') => return Ok(s),
                Some('\\') => match self.bump() {
                    Some('"') => s.push('"'),
                    Some('\\') => s.push('\\'),
                    Some('/') => s.push('/'),
                    Some('n') => s.push('\n'),
                    Some('t') => s.push('\t'),
                    Some('r') => s.push('\r'),
                    Some('b') => s.push('\u{0008}'),
                    Some('f') => s.push('\u{000C}'),
                    Some('u') => {
                        let mut code: u32 = 0;
                        for _ in 0..4 {
                            let d = match self.bump().and_then(|c| c.to_digit(16)) {
                                Some(d) => d,
                                None => return self.err("bad unicode escape"),
                            };
                            code = code * 16 + d;
                        }
                        match char::from_u32(code) {
                            Some(ch) => s.push(ch),
                            None => return self.err("bad unicode codepoint"),
                        }
                    }
                    _ => return self.err("bad escape"),
                },
                Some(c) => s.push(c),
            }
        }
    }

    fn parse_number(&mut self) -> Result<Value, ParseError> {
        let start = self.pos;
        if self.peek() == Some('-') {
            self.bump();
        }
        while let Some(c) = self.peek() {
            if c.is_ascii_digit() || matches!(c, '.' | 'e' | 'E' | '+' | '-') {
                self.bump();
            } else {
                break;
            }
        }
        let slice: String = self.chars[start..self.pos].iter().copied().collect();
        match slice.parse::<f64>() {
            Ok(n) => Ok(Value::Number(n)),
            Err(_) => self.err("invalid number"),
        }
    }

    fn parse_array(&mut self) -> Result<Value, ParseError> {
        self.bump(); // [
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == Some(']') {
            self.bump();
            return Ok(Value::Array(items));
        }
        loop {
            items.push(self.parse_value()?);
            self.skip_ws();
            match self.bump() {
                Some(',') => continue,
                Some(']') => return Ok(Value::Array(items)),
                _ => return self.err("expected ',' or ']'"),
            }
        }
    }

    fn parse_object(&mut self) -> Result<Value, ParseError> {
        self.bump(); // {
        let mut members = Vec::new();
        self.skip_ws();
        if self.peek() == Some('}') {
            self.bump();
            return Ok(Value::Object(members));
        }
        loop {
            self.skip_ws();
            if self.peek() != Some('"') {
                return self.err("expected string key");
            }
            let key = self.parse_string()?;
            self.skip_ws();
            if self.bump() != Some(':') {
                return self.err("expected ':'");
            }
            let value = self.parse_value()?;
            members.push((key, value));
            self.skip_ws();
            match self.bump() {
                Some(',') => continue,
                Some('}') => return Ok(Value::Object(members)),
                _ => return self.err("expected ',' or '}'"),
            }
        }
    }
}

pub fn parse(input: &str) -> Result<Value, ParseError> {
    let mut p = Parser { chars: input.chars().collect(), pos: 0 };
    let value = p.parse_value()?;
    p.skip_ws();
    if p.pos != p.chars.len() {
        return p.err("trailing characters");
    }
    Ok(value)
}
