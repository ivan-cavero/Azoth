//! `regiond`: the region's identity and login surface.
//!
//! WHY THIS BINARY EXISTS
//! ======================
//! `channeld` gets the client to the login screen and stops there: it serves the channel document
//! and says so explicitly when a login route is asked for. The next arrow in the client's login
//! ladder is the token exchange, then credentials, entitlements, privacy, `getlogininfo`, the world
//! list and the queue ticket — all of which are **identity**, not content, and all of which the
//! Python gateway answers today. This binary is that half, so the client can reach character select
//! with the Python gateway stopped.
//!
//! WHAT IT OWNS
//! ============
//! The seeded account, its persona, its character directory rows and the region/world registry they
//! are bound to (`identity`), and the HTTP surface that serves them (`routes`). It does **not** own
//! the channel document, CMS content or images — those stay in `channeld` — and it does not own live
//! character state, which belongs to the world server.
//!
//! WHY THE CLIENT RULES ARE NOT HERE
//! =================================
//! Every client-specific HTTP behaviour lives in `azoth-http` as a pure function with a test: the
//! `x-amzn-*` envelope, the content types, the route matcher and its measured quirks, the
//! Python-shaped JSON bytes. This binary wires them to a socket and states, in each module, which
//! measured client behaviour forces each shape.

pub mod config;
pub mod identity;
pub mod routes;

use std::net::SocketAddr;
use std::sync::Arc;

use config::Config;
use identity::Identity;
use routes::AppState;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::from_args(std::env::args().skip(1))?;
    let identity = Identity::load(&config)?;

    // Report what was loaded before serving: a region that starts with no character and says nothing
    // looks identical to one that is working.
    eprintln!("[regiond] {}", identity.summary());

    let app = routes::router(Arc::new(AppState::new(Arc::new(identity), config.ticket_out.clone())));
    let addr: SocketAddr = format!("{}:{}", config.host, config.port).parse()?;
    let listener = listener_with_nodelay(addr).await?;
    eprintln!("[regiond] listening {addr}");

    axum::serve(listener, app).await?;
    Ok(())
}

/// Build the listening socket with `TCP_NODELAY` set.
///
/// WHY THIS IS HERE AND NOT IN THE ROUTER: it is socket setup, not a route. Without it the
/// headers-plus-body write hits Windows delayed-ACK/Nagle and the region ping the client **displays
/// in its UI** measured 40–70 ms on loopback instead of ~2 ms (`azoth_http`'s second measured rule).
/// Axum does not set it, so the socket is configured before the handshake.
///
/// # Errors
/// The bind failure, unchanged.
async fn listener_with_nodelay(addr: SocketAddr) -> std::io::Result<tokio::net::TcpListener> {
    let socket = if addr.is_ipv4() {
        tokio::net::TcpSocket::new_v4()?
    } else {
        tokio::net::TcpSocket::new_v6()?
    };
    socket.set_nodelay(true)?;
    socket.bind(addr)?;
    socket.listen(1024)
}
