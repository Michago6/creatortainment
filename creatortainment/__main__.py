from .cli import main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc
