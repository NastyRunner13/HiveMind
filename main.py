"""
HiveMind — AI Team Intelligence Agent

Main entry point for running the HiveMind backend server.

Usage:
    python main.py                   # Start with default settings
    python main.py --host 0.0.0.0    # Bind to all interfaces
    python main.py --port 8080       # Custom port
    python main.py --reload          # Auto-reload on code changes (dev)

The server can also be started directly via uvicorn:
    uvicorn backend.app.main:app --reload
"""

import argparse
import sys
import os

# Ensure the backend directory is in the Python path
# so that `app.main:app` can be resolved when running from the project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the HiveMind server."""
    parser = argparse.ArgumentParser(
        description="🐝 HiveMind — AI Team Intelligence Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                  Start with defaults (localhost:8000)
  python main.py --reload         Start with auto-reload (development)
  python main.py --host 0.0.0.0   Bind to all network interfaces
  python main.py --port 8080      Use a custom port
        """,
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind the server to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the server to (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-reload on code changes (development mode)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (default: 1, use >1 for production)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Uvicorn log level (default: info)",
    )
    return parser.parse_args()


def main() -> None:
    """Start the HiveMind backend server using Uvicorn."""
    args = parse_args()

    try:
        import uvicorn
    except ImportError:
        print(
            "❌ uvicorn is not installed. "
            "Run: pip install -r backend/requirements.txt"
        )
        sys.exit(1)

    print(
        f"\n"
        f"  🐝 HiveMind — AI Team Intelligence Agent\n"
        f"  ─────────────────────────────────────────\n"
        f"  Host:    {args.host}\n"
        f"  Port:    {args.port}\n"
        f"  Reload:  {'enabled' if args.reload else 'disabled'}\n"
        f"  Workers: {args.workers}\n"
        f"  Docs:    http://{args.host}:{args.port}/docs\n"
        f"\n"
    )

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
