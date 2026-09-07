from __future__ import annotations

import argparse
import json
from typing import Any

from healthos.config import Settings
from healthos.google_health import GoogleOAuthClient
from healthos.http_client import JsonHttpClient
from healthos.job import HealthOSJob


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="healthos")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Sync data and send one coach email")
    run_parser.add_argument("--mode", choices=["auto", "morning", "evening"], default="auto")
    run_parser.add_argument("--days", type=int)
    run_parser.add_argument("--force", action="store_true")
    run_parser.set_defaults(func=_run)

    sync_parser = subparsers.add_parser("sync", help="Sync data without sending email")
    sync_parser.add_argument("--days", type=int, default=30)
    sync_parser.set_defaults(func=_sync)

    cleanup_parser = subparsers.add_parser("cleanup", help="Delete old raw health records")
    cleanup_parser.add_argument("--raw-days", type=int, default=30)
    cleanup_parser.set_defaults(func=_cleanup)

    oauth_url_parser = subparsers.add_parser("oauth-url", help="Print a Google OAuth URL")
    oauth_url_parser.add_argument("--redirect-uri", required=True)
    oauth_url_parser.set_defaults(func=_oauth_url)

    exchange_parser = subparsers.add_parser("exchange-code", help="Exchange an OAuth code")
    exchange_parser.add_argument("--code", required=True)
    exchange_parser.add_argument("--redirect-uri", required=True)
    exchange_parser.set_defaults(func=_exchange_code)

    auth_local_parser = subparsers.add_parser("auth-local", help="Run a localhost OAuth callback")
    auth_local_parser.add_argument("--redirect-uri", default="http://127.0.0.1:8080/callback")
    auth_local_parser.set_defaults(func=_auth_local)

    args = parser.parse_args(argv)
    result = args.func(args)
    if result is not None:
        print(result)
    return 0


def _run(args: argparse.Namespace) -> str:
    settings = Settings.from_env()
    return HealthOSJob.from_settings(settings).run(
        mode=args.mode,
        days=args.days,
        force=args.force,
    )


def _sync(args: argparse.Namespace) -> str:
    settings = Settings.from_env()
    return HealthOSJob.from_settings(settings).sync_only(days=args.days)


def _cleanup(args: argparse.Namespace) -> str:
    settings = Settings.from_env()
    return HealthOSJob.from_settings(settings).cleanup_raw_records(raw_days=args.raw_days)


def _oauth(settings: Settings) -> GoogleOAuthClient:
    return GoogleOAuthClient(JsonHttpClient(), settings.google_client_id, settings.google_client_secret)


def _oauth_url(args: argparse.Namespace) -> str:
    settings = Settings.from_env()
    oauth = _oauth(settings)
    return oauth.authorization_url(args.redirect_uri, settings.google_scopes)


def _exchange_code(args: argparse.Namespace) -> str:
    settings = Settings.from_env()
    oauth = _oauth(settings)
    token = oauth.exchange_code(args.code, args.redirect_uri)
    return _format_token_response(token)


def _auth_local(args: argparse.Namespace) -> str:
    settings = Settings.from_env()
    oauth = _oauth(settings)
    url = oauth.authorization_url(args.redirect_uri, settings.google_scopes)
    print("Open this URL and approve access:")
    print(url)
    token = oauth.run_local_authorization(
        redirect_uri=args.redirect_uri,
        scopes=settings.google_scopes,
    )
    return _format_token_response(token)


def _format_token_response(token: dict[str, Any]) -> str:
    return json.dumps(
        {
            "refresh_token": token.get("refresh_token"),
            "access_token_present": bool(token.get("access_token")),
            "expires_in": token.get("expires_in"),
            "scope": token.get("scope"),
        },
        indent=2,
        sort_keys=True,
    )
