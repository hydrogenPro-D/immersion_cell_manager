import sys
import threading

from src.splash import Splash, asset_path, claim_taskbar_identity


def _load(result: dict, done: threading.Event) -> None:
    # Runs on a worker thread so the splash keeps pulsing: imports the GUI, then
    # connects and loads the data (managers hold no Qt objects).
    try:
        from src.gui.gui import load_managers, run_app
        result["run_app"] = run_app
        try:
            result["managers"] = load_managers()
        except Exception as exc:  # e.g. DatabaseError; run_app reports it
            result["load_error"] = exc
    except BaseException as exc:
        result["error"] = exc
    finally:
        done.set()


def main() -> None:
    claim_taskbar_identity()  # before QApplication: Windows binds the button to the first window

    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(asset_path("app_icon.ico"))))
    splash = Splash()
    splash.show()
    app.processEvents()

    result, done = {}, threading.Event()
    threading.Thread(target=_load, args=(result, done), daemon=True).start()
    while not done.wait(0.01):
        app.processEvents()
    if "error" in result:
        splash.close_now()
        raise result["error"]
    result["run_app"](app, splash, result.get("managers"), result.get("load_error"))


if __name__ == "__main__":
    main()
