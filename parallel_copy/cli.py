"""
CLI interface for parallel_copy project.
"""

import argparse
import concurrent.futures
import functools
import logging
import os
import queue
import shutil
import sys
import threading
from pathlib import Path

from tqdm.auto import tqdm

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def human_readable_size(size: int) -> str:
    """Convert bytes to a human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


class ParallelCopy:
    _pbar_update_freq = 1

    _file_count = 0  # number of copied files
    _total_size = 0  # total size of copied files, in bytes
    _skipped_count = 0  # number of skipped files

    def __init__(
        self,
        src: str,
        dest: str,
        threads: int = 4,
        follow_symlinks: bool = True,
        shallow_compare: bool = False,
    ):
        self.src = Path(src)
        if not self.src.exists():
            raise FileNotFoundError(f"Source directory {self.src} does not exist.")

        self.dest = Path(dest)
        self.threads = threads
        self.follow_symlinks = follow_symlinks
        self.shallow_compare = shallow_compare

        self.count_lock = threading.Lock()

        self.reset()

    def reset(self):
        self._file_count = 0
        self._total_size = 0
        self._skipped_count = 0
        self._progress_bar = tqdm(
            unit="file",
            desc="Copying files",
            dynamic_ncols=True,
        )
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.threads)

    def dfs_copy(self, current_src: Path):
        rel_path = current_src.relative_to(self.src)
        current_dst = self.dest / rel_path
        current_dst.mkdir(exist_ok=True)

        for entry in current_src.iterdir():
            src_path = entry
            dst_path = current_dst / entry.name

            if (sys.platform == "win32" and entry.is_dir()) or entry.is_dir(
                follow_symlinks=self.follow_symlinks
            ):
                self.dfs_copy(src_path)
            elif (sys.platform == "win32" and entry.is_file()) or entry.is_file(
                follow_symlinks=self.follow_symlinks
            ):
                # Submit the copy task to the thread pool
                log.debug(f"Copying {src_path} to {dst_path}")
                self.pool.submit(functools.partial(self.copy_file, src_path, dst_path))

    def copy_file(self, src_path: Path, dst_path: Path):
        """copy a single file, and update progress bar."""
        assert src_path.is_file(), f"{src_path} is not a file"
        # sleep 1s
        import time

        time.sleep(1)

        if dst_path.exists() and dst_path.is_file():
            if self.shallow_compare:
                try:
                    if (
                        src_path.stat().st_size == dst_path.stat().st_size
                        and src_path.stat().st_mtime == dst_path.stat().st_mtime
                    ):
                        print(f"\rSkipping {src_path} (already exists)")
                        with self.count_lock:
                            self._skipped_count += 1
                            self._file_count += 1
                            self._total_size += src_path.stat().st_size
                            self._update_progress_bar()
                        return
                except PermissionError:
                    log.error(f"PermissionError: {src_path} or {dst_path}, skipping.")
                except Exception as e:
                    log.error(f"Error comparing files: {e}, skipping.")
        try:
            print(
                f"\r{src_path} \tsize: {human_readable_size(src_path.stat().st_size)}"
            )
            shutil.copy2(src_path, dst_path)
        except PermissionError:
            log.error(f"PermissionError: {src_path} or {dst_path}, skipping.")
        except Exception as e:
            log.error(f"Error copying file: {e}, skipping.")

        with self.count_lock:
            self._file_count += 1
            self._total_size += src_path.stat().st_size
            self._update_progress_bar()

    def _update_progress_bar(self, skip_check=False):
        if skip_check or self._file_count % self._pbar_update_freq == 0:
            self._progress_bar.update(self._pbar_update_freq)
            self._progress_bar.set_postfix(
                {
                    "total": self._file_count,
                    "size": human_readable_size(self._total_size),
                    "skipped": f"{self._skipped_count}",
                }
            )

    def __call__(self):
        self.dfs_copy(self.src)
        self._update_progress_bar(skip_check=True)

        # clean up
        self.pool.shutdown(wait=True)
        self._progress_bar.close()


def parse_args():
    parser = argparse.ArgumentParser(description="parallel_copy CLI")
    # src directory and dest directory, positional arguments that are required
    parser.add_argument("src", type=str, help="Source directory")
    parser.add_argument("dest", type=str, help="Destination directory")
    # optional argument for number of threads, default is 4
    parser.add_argument(
        "-t", "--threads", type=int, default=4, help="Number of threads to use"
    )
    parser.add_argument(
        "--shallow-compare", action="store_true", help="Use shallow compare"
    )
    args = parser.parse_args()
    return args


def main():  # pragma: no cover
    """
    The main function executes on commands:
    `python -m parallel_copy` and `$ parallel_copy `.

    This is your program's entry point.

    You can change this function to do whatever you want.
    Examples:
        * Run a test suite
        * Run a server
        * Do some other stuff
        * Run a command line application (Click, Typer, ArgParse)
        * List all available tasks
        * Run an application (Flask, FastAPI, Django, etc.)
    """
    args = parse_args()
    program = ParallelCopy(
        src=args.src,
        dest=args.dest,
        threads=args.threads,
        shallow_compare=args.shallow_compare,
    )
    program()


if __name__ == "__main__":
    main()
