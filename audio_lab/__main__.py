import sys


def main() -> int:
    if "--demo-screenshot" in sys.argv:
        # developer-only screenshot tooling — see audio_lab/demo.py
        from audio_lab.demo import DEFAULT_CAPTURE, run_demo

        return run_demo(capture_path=DEFAULT_CAPTURE)
    from audio_lab.app import main as app_main

    return app_main()


sys.exit(main())
