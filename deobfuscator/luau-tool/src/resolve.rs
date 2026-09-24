//! Lexical scope resolution.
//!
//! Emits every variable-name token in source order as
//! `[start, end, name, target, is_decl]`, where `target` is the index of the
//! declaration it binds to (itself for declarations) or -1 for free names.
//! Field names (`a.b`, `{b = 1}`, `a:b()`) are not variables and are skipped.

use std::collections::{HashMap, HashSet};

use full_moon::ast::{
    Ast, Block, FunctionBody, FunctionDeclaration, GenericFor, LocalAssignment, LocalFunction,
    NumericFor, Parameter, Prefix, Repeat, Var,
};
use full_moon::node::Node;
use full_moon::tokenizer::TokenReference;
use full_moon::visitors::Visitor;
use serde_json::json;

struct Name {
    start: usize,
    end: usize,
    name: String,
    target: i64,
    is_decl: bool,
}

#[derive(Default)]
struct Resolver {
    names: Vec<Name>,
    decl_count: i64,
    /// each scope maps a name to its declaration index
    scopes: Vec<HashMap<String, i64>>,
    /// declarations (name, start, end) that enter scope when a given block starts
    pending: HashMap<usize, Vec<(String, usize, usize)>>,
    /// repeat bodies stay open until the `until` condition is done
    repeat_bodies: HashSet<usize>,
    /// ranges of `local function fN` / `function fN` definitions
    functions: Vec<(String, usize, usize)>,
}

fn token_span(tok: &TokenReference) -> (String, usize, usize) {
    (tok.token().to_string(), tok.token().start_position().bytes(),
     tok.token().end_position().bytes())
}

fn ptr(b: &Block) -> usize {
    b as *const Block as usize
}

impl Resolver {
    fn declare(&mut self, tok: &TokenReference) {
        let (name, start, end) = token_span(tok);
        self.declare_raw(name, start, end);
    }

    fn declare_raw(&mut self, name: String, start: usize, end: usize) {
        let id = self.decl_count;
        self.decl_count += 1;
        self.names.push(Name { start, end, name: name.clone(), target: id, is_decl: true });
        self.scopes.last_mut().unwrap().insert(name, id);
    }

    fn reference(&mut self, tok: &TokenReference) {
        let name = tok.token().to_string();
        let target = self
            .scopes
            .iter()
            .rev()
            .find_map(|s| s.get(&name).copied())
            .unwrap_or(-1);
        self.names.push(Name {
            start: tok.token().start_position().bytes(),
            end: tok.token().end_position().bytes(),
            name,
            target,
            is_decl: false,
        });
    }

    fn pend(&mut self, block: &Block, decl: (String, usize, usize)) {
        self.pending.entry(ptr(block)).or_default().push(decl);
    }
}

impl Visitor for Resolver {
    fn visit_block(&mut self, block: &Block) {
        self.scopes.push(HashMap::new());
        for (name, start, end) in self.pending.remove(&ptr(block)).unwrap_or_default() {
            self.declare_raw(name, start, end);
        }
    }

    fn visit_block_end(&mut self, block: &Block) {
        if !self.repeat_bodies.contains(&ptr(block)) {
            self.scopes.pop();
        }
    }

    fn visit_repeat(&mut self, node: &Repeat) {
        self.repeat_bodies.insert(ptr(node.block()));
    }

    fn visit_repeat_end(&mut self, _node: &Repeat) {
        self.scopes.pop();
    }

    fn visit_function_body(&mut self, body: &FunctionBody) {
        let params: Vec<_> = body
            .parameters()
            .iter()
            .filter_map(|p| match p {
                Parameter::Name(t) => Some(token_span(t)),
                _ => None,
            })
            .collect();
        for p in params {
            self.pend(body.block(), p);
        }
    }

    fn visit_local_function(&mut self, node: &LocalFunction) {
        // the name is in scope inside its own body (recursion)
        self.declare(node.name());
        let n = node.name().token().to_string();
        self.functions.push((n, node.start_position().unwrap().bytes(),
                             node.end_position().unwrap().bytes()));
    }

    fn visit_function_declaration(&mut self, node: &FunctionDeclaration) {
        let fname = node.name();
        let first = fname.names().iter().next().unwrap().clone();
        self.reference(&first);
        if let Some(colon) = fname.method_colon() {
            // implicit `self`: a zero-width declaration at the colon
            let at = colon.token().start_position().bytes();
            self.pend(node.body().block(), ("self".into(), at, at));
        }
        if fname.names().len() == 1 && fname.method_colon().is_none() {
            self.functions.push((first.token().to_string(),
                                 node.start_position().unwrap().bytes(),
                                 node.end_position().unwrap().bytes()));
        }
    }

    fn visit_local_assignment_end(&mut self, node: &LocalAssignment) {
        // `local x = x`: the right-hand side still sees the outer x
        for name in node.names().iter() {
            self.declare(name);
        }
    }

    fn visit_numeric_for(&mut self, node: &NumericFor) {
        self.pend(node.block(), token_span(node.index_variable()));
    }

    fn visit_generic_for(&mut self, node: &GenericFor) {
        for n in node.names().iter() {
            self.pend(node.block(), token_span(n));
        }
    }

    fn visit_var(&mut self, var: &Var) {
        if let Var::Name(t) = var {
            self.reference(t);
        }
    }

    fn visit_prefix(&mut self, prefix: &Prefix) {
        if let Prefix::Name(t) = prefix {
            self.reference(t);
        }
    }
}

pub fn run(src: &str) -> String {
    let ast: Ast = full_moon::parse_fallible(src, full_moon::LuaVersion::luau())
        .into_result()
        .unwrap_or_else(|errs| panic!("parse errors: {errs:?}"));
    let mut r = Resolver::default();
    r.scopes.push(HashMap::new());
    r.visit_ast(&ast);
    r.names.sort_by_key(|n| (n.start, n.end));
    let names: Vec<_> = r
        .names
        .iter()
        .map(|n| json!([n.start, n.end, n.name, n.target, n.is_decl as u8]))
        .collect();
    let functions: Vec<_> = r.functions.iter().map(|(n, s, e)| json!([n, s, e])).collect();
    json!({ "names": names, "functions": functions }).to_string()
}
