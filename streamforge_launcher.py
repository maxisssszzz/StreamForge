import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--streamforge-yt-dlp":
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        from yt_dlp import main as yt_dlp_main

        return yt_dlp_main()

    from streamforge_server import run_server

    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
