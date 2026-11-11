"""Remote selection against a bounded synthetic tree; no SSH; isolated temporary paths."""

from __future__ import annotations

import fnmatch
import stat
import sys
from types import SimpleNamespace


def check_input(data: bytes) -> None:
    from colosseum_messaging.ssh._file_select import select_remote_files
    from colosseum_messaging.ssh._remote_path import (
        normalize_remote_path,
        remote_basename,
        remote_dirname,
        split_remote_path,
    )

    data = data[:512]
    flags = data[0] if data else 0
    payload = data[1:]
    drive = "C:" if flags & 1 else ""
    root = drive + "/logs"
    # Distinct names and finite timestamps keep ties and ordering reproducible.
    files = []
    directories = {root: []}
    for index, value in enumerate(payload[:12]):
        depth = value % 3
        parent = root
        for level in range(depth):
            child = parent + f"/sub{level}"
            if child not in directories:
                directories[parent].append(
                    SimpleNamespace(
                        filename=f"sub{level}",
                        st_mode=stat.S_IFDIR,
                        st_mtime=0,
                    ),
                )
                directories[child] = []
            parent = child
        name = f"File{index}." + ("LOG" if value & 4 else "txt")
        mtime = float(value)
        directories[parent].append(
            SimpleNamespace(
                filename=name,
                st_mode=stat.S_IFREG,
                st_mtime=mtime,
            ),
        )
        files.append((parent + "/" + name, mtime, depth))

    class Lister:
        def listdir_attr(self, path):
            return directories[path]

    # Always exercise glob traversal, including malformed bracket patterns.
    pattern = (
        "*",
        "*.txt",
        "*.log",
        "File?.*",
        "[!F]*",
        "[",
        "*" + payload.decode("utf-8", errors="replace").replace("/", "").replace("\\", ""),
    )[(flags >> 1) % 7]
    # Remote specifications are stripped before basename matching.
    pattern = pattern.rstrip()
    recursive = bool(flags & 16)
    max_depth = (None, 0, 1, 2)[(flags >> 5) % 4]
    sensitive = bool(flags & 128)
    expected = []
    for path, mtime, depth in files:
        name = path.rsplit("/", 1)[1]
        if not sensitive:
            name = name.lower()
        match_pattern = pattern if sensitive else pattern.lower()
        if (depth == 0 or recursive and (max_depth is None or depth <= max_depth)) and (
            fnmatch.fnmatchcase(name, match_pattern)
        ):
            expected.append((path, mtime))
    options = {"recursive": recursive, "max_depth": max_depth, "case_sensitive": sensitive}
    actual = select_remote_files(Lister(), root + "/" + pattern, **options)
    assert sorted(actual) == sorted(expected)
    limit = flags % 5
    for keyword, reverse in (("newest", True), ("oldest", False)):
        selected = select_remote_files(
            Lister(),
            root + "/" + pattern,
            **options,
            **{keyword: limit},
        )
        # Preserve traversal order for equal timestamps rather than impose a new tie policy.
        assert selected == sorted(actual, key=lambda item: item[1], reverse=reverse)[:limit]

    check_mappings(flags, root, files)

    for path, _mtime, _depth in files:
        mixed = path.replace("/", "\\")
        assert normalize_remote_path(mixed) == path
        assert normalize_remote_path(path) == path
        assert remote_basename(mixed) == path.rsplit("/", 1)[1]
        assert remote_dirname(mixed) == path.rsplit("/", 1)[0]
        assert split_remote_path(mixed) == split_remote_path(path)


def check_mappings(flags, remote_root, files) -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    from colosseum_messaging import _paths
    from colosseum_messaging.ssh._file_select import map_local_put_paths, map_remote_get_paths

    assert map_remote_get_paths([], remote_root + "/*", "unused", resolve_local=Path) == []
    assert map_local_put_paths([], "unused", "/upload") == []
    if not files:
        return
    with TemporaryDirectory(prefix="colosseum-mapping-") as directory:
        root = Path(directory).resolve() / "run"
        root.mkdir()
        sources = root / "sources"
        relative = [path[len(remote_root) + 1 :] for path, _time, _depth in files]
        local_files = [sources / part for part in relative]
        spec = str(sources / "*") if flags & 1 else str(sources) + "/"
        if len(local_files) == 1 and flags & 4:
            spec = str(local_files[0])
            expected_relative = [local_files[0].name]
        else:
            expected_relative = relative
        destination = "/upload/" if flags & 2 else "/upload"
        uploads = map_local_put_paths(local_files, spec, destination)
        expected = (
            ["/upload"]
            if len(local_files) == 1 and not flags & 2
            else ["/upload/" + name for name in expected_relative]
        )
        assert uploads == list(zip(local_files, expected))

        context = SimpleNamespace(test_case_name="fuzz")
        with (
            patch.object(_paths, "get_context", return_value=context),
            patch.object(
                _paths,
                "ensure_output_dir",
                return_value=root,
            ),
        ):
            remote_files = [path for path, _time, _depth in files]
            downloads = map_remote_get_paths(
                remote_files,
                remote_root + "/*",
                "downloads",
                resolve_local=_paths.resolve_artifact_path,
            )
            assert downloads == list(zip(remote_files, [root / "downloads" / p for p in relative]))
            assert all(path.relative_to(root) for _source, path in downloads)
            assert all(path.parent.is_dir() for _source, path in downloads)
            one = map_remote_get_paths(
                remote_files[:1],
                remote_files[0],
                "renamed.txt",
                resolve_local=_paths.resolve_artifact_path,
            )
            assert one == [(remote_files[0], root / "renamed.txt")]
            bad_cases = (
                (remote_files[:1], remote_root + "/*", "../run-other"),
                (
                    [remote_root + "/" + "../" * (2 + flags % 4) + "escape.txt"],
                    remote_root + "/*",
                    "downloads",
                ),
                (remote_files[:1], remote_root + "/*", "multiple.txt"),
            )
            for paths, remote_spec, local in bad_cases:
                try:
                    map_remote_get_paths(
                        paths,
                        remote_spec,
                        local,
                        resolve_local=_paths.resolve_artifact_path,
                    )
                except ValueError:
                    pass
                else:
                    raise AssertionError("Invalid download destination accepted")
            assert not (root.parent / "run-other").exists()
            assert not (root.parent / "escape.txt").exists()


def main() -> None:
    import atheris

    with atheris.instrument_imports(include=["colosseum_messaging"]):
        import colosseum_messaging._paths  # noqa: F401
        import colosseum_messaging.ssh._file_select  # noqa: F401
    atheris.Setup(sys.argv, atheris.instrument_func(check_input))
    atheris.Fuzz()


if __name__ == "__main__":
    main()
