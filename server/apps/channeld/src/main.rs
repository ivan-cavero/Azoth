//! `channeld`: the HTTP entry point.
//!
//! WHY THIS BINARY EXISTS, AND WHY IT IS FIRST
//! ==========================================
//! The client cannot do anything until it has read the channel document, and every later phase
//! (region, world, gameplay) assumes a working HTTP entry. That makes this the smallest complete
//! vertical: it is the only piece that can be replaced end to end and verified by a client reaching
//! the login screen with the Python gateway stopped.
//!
//! WHAT IT OWNS
//! ============
//! Content and caching. It changes when we publish a news item, and it must serve while every world
//! is down. It does **not** own identity or the queue — those belong to a region, and putting them
//! here would make one process the only thing between a player and the game.
//!
//! THE RULES ARE NOT HERE
//! ======================
//! Every client-specific HTTP behaviour lives in `azoth-http` as a pure function with a test:
//! ETags, `If-None-Match`, the `x-amzn-*` envelope, the route matcher and its measured quirks.
//! This binary wires them to a socket. That split is what lets the rules be verified without
//! starting a server, and it is why this file can stay small.

pub mod config;
pub mod images;
pub mod routes;
pub mod state;

use std::net::SocketAddr;

use config::Config;
use state::AppState;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::from_args(std::env::args().skip(1))?;
    let state = AppState::load(&config)?;

    // Report what was loaded before serving: a gateway that starts with an empty registry and says
    // nothing looks identical to one that is working.
    let summary = state.summary();
    eprintln!("[channeld] {summary}");

    let app = routes::router(state);
    let addr: SocketAddr = format!("{}:{}", config.host, config.port).parse()?;
    let listener = tokio::net::TcpListener::bind(addr).await?;
    eprintln!("[channeld] listening {addr}");

    axum::serve(listener, app).await?;
    Ok(())
}
