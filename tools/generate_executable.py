"""Generate an executable from the Immersion Cell Manager application using PyInstaller."""

from pathlib import Path
import subprocess
import sys
import shutil
import stat
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
ENTRY_SCRIPT = PROJECT_ROOT / "main.py"
SPEC_PATH = TOOLS_DIR
DIST_PATH = PROJECT_ROOT / "dist"
WORK_PATH = PROJECT_ROOT / "build"
EXECUTABLE_NAME = "Immersion Cell Manager"
HIDDEN_IMPORTS = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
]
SPEC_FILENAME = f"{EXECUTABLE_NAME}.spec"
SPEC_FILE = SPEC_PATH / SPEC_FILENAME
DATA_FOLDER = PROJECT_ROOT / "src" / "data" / "csv"
TEMPLATE_FILE = DATA_FOLDER / "immersion_cells_template.csv"
DRIVER_FOLDER = PROJECT_ROOT / "driver"
CONFIG_FOLDER = PROJECT_ROOT / "config"
EXECUTABLE_FOLDER = DIST_PATH / EXECUTABLE_NAME


def _run_pyinstaller(command: list[str]) -> None:
    """Run PyInstaller with the given command.

    Args:
        command: List of command arguments to pass to PyInstaller
    """
    print("Running:", " ".join(command))
    result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    if result.returncode != 0:
        print(f"PyInstaller failed with exit code {result.returncode}")
        raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout, stderr=result.stderr)


def _delete_folder(folder_path: Path) -> None:
    """Delete a folder and all its contents if it exists.

    Args:
        folder_path: Path to the folder to delete
    """
    if folder_path.exists():
        print(f"Deleting folder: {folder_path}")

        def handle_remove_error(func, path, exc_info):
            """Error handler for shutil.rmtree to handle permission issues."""
            try:
                if not os.access(path, os.W_OK):
                    os.chmod(path, stat.S_IWUSR | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                func(path)
            except Exception:
                pass

        try:
            shutil.rmtree(folder_path, onerror=handle_remove_error)
            print(f"Successfully deleted: {folder_path}")
            return
        except Exception as e:
            print(f"Warning: Standard deletion failed: {e}")
            print("Attempting alternative deletion method...")

        # Strategy 2: Manual file-by-file and directory deletion
        try:
            # Collect all items with their depths
            items_to_remove = []
            for item in folder_path.rglob("*"):
                depth = len(item.relative_to(folder_path).parts)
                items_to_remove.append((depth, item))

            # Sort by depth (deepest first)
            items_to_remove.sort(key=lambda x: -x[0])

            # Remove all files
            files_removed = 0
            for depth, item in items_to_remove:
                if item.is_file():
                    try:
                        item.chmod(0o777)
                        item.unlink()
                        files_removed += 1
                    except Exception as item_err:
                        print(f"  Warning: Could not remove file {item.name}: {item_err}")

            print(f"  Removed {files_removed} files")

            # Remove all directories (in reverse depth order)
            dirs_to_remove = [(depth, item) for depth, item in items_to_remove if item.is_dir()]
            dirs_to_remove.sort(key=lambda x: -x[0])  # Deepest first

            dirs_removed = 0
            for depth, item in dirs_to_remove:
                try:
                    item.chmod(0o777)
                    os.rmdir(item)
                    dirs_removed += 1
                except Exception as dir_err:
                    print(f"  Warning: Could not remove directory {item.name}: {dir_err}")

            print(f"  Removed {dirs_removed} directories")

            # Finally remove the root folder
            try:
                folder_path.chmod(0o777)
                os.rmdir(folder_path)
                print(f"Successfully deleted: {folder_path}")
                return
            except Exception as root_err:
                print(f"  Warning: Could not remove root directory: {root_err}")

        except Exception as e2:
            print(f"Warning: Alternative deletion method also failed: {e2}")

        # Strategy 3: Use Windows cmd if available
        if sys.platform == "win32":
            print("Attempting Windows-specific deletion using cmd...")
            try:
                import subprocess
                result = subprocess.run(
                    ["cmd", "/c", "rmdir", "/s", "/q", str(folder_path)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    print(f"Successfully deleted: {folder_path}")
                    return
                else:
                    print(f"  cmd deletion failed: {result.stderr}")
            except Exception as cmd_err:
                print(f"  cmd deletion error: {cmd_err}")

        # If we get here, raise the original error
        print(f"Error: Could not delete {folder_path}")
        print("Note: The directory may still contain locked files. Try:")
        print(f"  1. Closing any applications using files from: {folder_path}")
        print(f"  2. Running this script with administrator privileges")
        print(f"  3. Manually deleting: {folder_path}")
        raise Exception(f"Failed to delete {folder_path}")
    else:
        print(f"Folder does not exist (skipping): {folder_path}")


def _copy_file(src: Path, dst: Path) -> None:
    """Copy a single file to a destination, creating parent directories if needed.

    Args:
        src: Source file path
        dst: Destination file path
    """
    if src.exists():
        print(f"Copying file: {src} -> {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"Successfully copied: {dst}")
    else:
        print(f"Source file does not exist (skipping): {src}")


def _copy_folder(src: Path, dst: Path) -> None:
    """Copy an entire folder and all its contents to a destination.

    Args:
        src: Source folder path
        dst: Destination folder path
    """
    if src.exists() and src.is_dir():
        print(f"Copying folder: {src} -> {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"Successfully copied: {dst}")
    else:
        print(f"Source folder does not exist (skipping): {src}")


def _build_from_existing_spec() -> None:
    """Build executable using an existing spec file."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        str(SPEC_FILE),
    ]
    print(f"Using existing spec (no regeneration): {SPEC_FILE}")
    _run_pyinstaller(command)


def _bootstrap_spec() -> None:
    """Bootstrap a new spec file and build the executable."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name",
        EXECUTABLE_NAME,
        "--specpath",
        str(SPEC_PATH),
        "--distpath",
        str(DIST_PATH),
        "--workpath",
        str(WORK_PATH),
    ]

    for hidden_import in HIDDEN_IMPORTS:
        command.extend(["--hidden-import", hidden_import])

    command.append(str(ENTRY_SCRIPT))

    print(f"Spec file not found. Bootstrapping a new one at: {SPEC_FILE}")
    _run_pyinstaller(command)


def build_executable() -> None:
    """Build the executable.

    If a spec file exists, use it. Otherwise, bootstrap a new spec file first.
    Then copies the template CSV file to the executable output directory,
    renaming it to immersion_cells.csv.

    Raises:
        FileNotFoundError: If the entry script (main.py) is not found.
    """
    if not ENTRY_SCRIPT.exists():
        raise FileNotFoundError(f"Could not find entry script: {ENTRY_SCRIPT}")

    if SPEC_FILE.exists():
        _build_from_existing_spec()
    else:
        _bootstrap_spec()

    # Copy template CSV file and rename it to immersion_cells.csv
    # PyInstaller with --onedir puts bundled modules in _internal/
    data_dest = EXECUTABLE_FOLDER / "_internal" / "src" / "data" / "csv"
    data_dest.mkdir(parents=True, exist_ok=True)

    if TEMPLATE_FILE.exists():
        dst_file = data_dest / "immersion_cells.csv"
        print(f"Copying template: {TEMPLATE_FILE} -> {dst_file}")
        shutil.copy2(TEMPLATE_FILE, dst_file)
        print(f"Successfully copied: {dst_file}")
    else:
        print(f"Template file does not exist (skipping): {TEMPLATE_FILE}")

    # Copy the ODBC driver folder so the app can install the driver on first run.
    # db.py resolves it as parents[2] of itself, which is _internal/ in the build.
    driver_dest = EXECUTABLE_FOLDER / "_internal" / "driver"
    _copy_folder(DRIVER_FOLDER, driver_dest)

    # Copy the config folder (db_config.json + example) so the frozen app can
    # read its DB credentials. db.py resolves it as parents[2]/config, which is
    # _internal/config in the build.
    config_dest = EXECUTABLE_FOLDER / "_internal" / "config"
    _copy_folder(CONFIG_FOLDER, config_dest)

    print(f"Build finished. Executable output is under: {DIST_PATH}")
    print(f"Spec file is at: {SPEC_FILE}")


if __name__ == "__main__":
    build_executable()


