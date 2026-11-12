"""Punto de entrada estable para PyInstaller (sin importaciones relativas)."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from clipstudio.__main__ import main
    raise SystemExit(main())
