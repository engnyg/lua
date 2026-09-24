//! Report opaque predicates: `V = not not C` and what the next statement
//! would do if the decompiled literal `C` were taken at face value.
//!
//! Nothing is rewritten: in this file `not not false` sometimes guards code
//! that must run (removing it would make the function always error), so the
//! literal cannot be trusted. See analysis.md.

use full_moon::ast::{Ast, BinOp, Block, Expression, Repeat, Stmt, UnOp, Var};
use full_moon::node::Node;
use full_moon::tokenizer::TokenReference;
use full_moon::visitors::Visitor;
use serde_json::{json, Value};

#[derive(Clone, Copy, PartialEq)]
enum Val {
    Nil,
    Bool(bool),
    Other,
}

impl Val {
    fn truthy(self) -> bool {
        !matches!(self, Val::Nil | Val::Bool(false))
    }
}

fn text(t: &TokenReference) -> String {
    t.token().to_string()
}
fn lines<N: Node>(n: &N) -> [usize; 2] {
    [n.start_position().unwrap().line(), n.end_position().unwrap().line()]
}

fn not_not_literal(e: &Expression) -> Option<bool> {
    if let Expression::UnaryOperator { unop: UnOp::Not(_), expression } = e {
        if let Expression::UnaryOperator { unop: UnOp::Not(_), expression } = &**expression {
            if let Expression::Symbol(t) = &**expression {
                return match text(t).as_str() {
                    "true" => Some(true),
                    "false" => Some(false),
                    _ => None,
                };
            }
        }
    }
    None
}

fn eval(e: &Expression, name: &str, c: bool) -> Option<Val> {
    match e {
        Expression::Symbol(t) => match text(t).as_str() {
            "true" => Some(Val::Bool(true)),
            "false" => Some(Val::Bool(false)),
            "nil" => Some(Val::Nil),
            _ => None,
        },
        Expression::Number(_) | Expression::String(_) => Some(Val::Other),
        Expression::Var(Var::Name(t)) if text(t) == name => Some(Val::Bool(c)),
        Expression::Parentheses { expression, .. } => eval(expression, name, c),
        Expression::UnaryOperator { unop: UnOp::Not(_), expression } => {
            eval(expression, name, c).map(|v| Val::Bool(!v.truthy()))
        }
        Expression::BinaryOperator { lhs, binop, rhs } => {
            let l = eval(lhs, name, c)?;
            match binop {
                BinOp::And(_) => if l.truthy() { eval(rhs, name, c) } else { Some(l) },
                BinOp::Or(_) => if l.truthy() { Some(l) } else { eval(rhs, name, c) },
                _ => None,
            }
        }
        _ => None,
    }
}

fn opaque_assignment(stmt: &Stmt) -> Option<(String, bool)> {
    match stmt {
        Stmt::Assignment(a) if a.variables().len() == 1 && a.expressions().len() == 1 => {
            let Some(Var::Name(name)) = a.variables().iter().next() else { return None };
            not_not_literal(a.expressions().iter().next().unwrap()).map(|c| (text(name), c))
        }
        Stmt::LocalAssignment(a) if a.names().len() == 1 && a.expressions().len() == 1 => {
            let name = a.names().iter().next().unwrap();
            not_not_literal(a.expressions().iter().next().unwrap()).map(|c| (text(name), c))
        }
        _ => None,
    }
}

#[derive(Default)]
struct Report {
    sites: Vec<Value>,
    /// repeat bodies already reported as a whole
    handled: std::collections::HashSet<usize>,
}

impl Report {
    fn site(&mut self, line: usize, name: &str, c: bool, construct: &str,
            reading: &str, dead: Option<[usize; 2]>) {
        self.sites.push(json!({
            "line": line, "var": name, "literal": c, "construct": construct,
            "literal_reading": reading, "dead_lines": dead,
        }));
    }

    fn after_assignment(&mut self, line: usize, name: &str, c: bool, next: Option<&Stmt>) {
        match next {
            Some(Stmt::If(n)) => match eval(n.condition(), name, c) {
                Some(v) if v.truthy() => {
                    // the first branch always runs; elseif/else parts never do
                    let dead = match (n.else_if(), n.else_token()) {
                        (Some(l), _) if !l.is_empty() => Some([
                            l[0].else_if_token().start_position().unwrap().line(),
                            n.end_token().start_position().unwrap().line(),
                        ]),
                        (_, Some(t)) => Some([
                            t.start_position().unwrap().line(),
                            n.end_token().start_position().unwrap().line(),
                        ]),
                        _ => None,
                    };
                    self.site(line, name, c, "if", "condition always true", dead)
                }
                Some(_) => {
                    // from `if` up to the first elseif/else, or the whole statement
                    let stop = match (n.else_if(), n.else_token()) {
                        (Some(l), _) if !l.is_empty() => lines(l[0].else_if_token())[0],
                        (_, Some(t)) => lines(t)[0],
                        _ => lines(n)[1],
                    };
                    let dead = [lines(n)[0], stop];
                    self.site(line, name, c, "if", "condition always false", Some(dead))
                }
                None => self.site(line, name, c, "if", "condition depends on other values", None),
            },
            Some(Stmt::While(n)) => match eval(n.condition(), name, c) {
                Some(v) if !v.truthy() => {
                    self.site(line, name, c, "while", "loop never runs", Some(lines(n)))
                }
                Some(_) => self.site(line, name, c, "while", "condition always true", None),
                None => self.site(line, name, c, "while", "condition depends on other values", None),
            },
            _ => self.site(line, name, c, "assignment", "value not tested by the next statement", None),
        }
    }

    fn repeat(&mut self, node: &Repeat) -> Option<(String, bool)> {
        let body = node.block();
        if body.last_stmt().is_some() || body.stmts().count() != 1 {
            return None;
        }
        let (name, c) = opaque_assignment(body.stmts().next().unwrap())?;
        self.handled.insert(body as *const Block as usize);
        let line = lines(node)[0];
        match eval(node.until(), &name, c) {
            Some(v) if v.truthy() => self.site(line, &name, c, "repeat", "runs once", None),
            Some(_) => self.site(line, &name, c, "repeat", "infinite loop", None),
            None => self.site(line, &name, c, "repeat", "condition depends on other values", None),
        }
        Some((name, c))
    }
}

impl Visitor for Report {
    fn visit_block(&mut self, block: &Block) {
        if self.handled.contains(&(block as *const Block as usize)) {
            return;
        }
        let stmts: Vec<&Stmt> = block.stmts().collect();
        for (i, stmt) in stmts.iter().enumerate() {
            if let Some((name, c)) = opaque_assignment(stmt) {
                self.after_assignment(lines(*stmt)[0], &name, c, stmts.get(i + 1).copied());
            } else if let Stmt::Repeat(r) = stmt {
                self.repeat(r);
            }
        }
    }
}

pub fn run(src: &str) -> String {
    let ast: Ast = full_moon::parse_fallible(src, full_moon::LuaVersion::luau())
        .into_result()
        .unwrap_or_else(|errs| panic!("parse errors: {errs:?}"));
    let mut r = Report::default();
    r.visit_ast(&ast);
    json!({ "sites": r.sites }).to_string()
}
