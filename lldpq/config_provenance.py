#!/usr/bin/env python3
"""Carry newly shipped notifications.yaml defaults onto a host without
overwriting anything its operator chose.

``notifications.yaml`` is preserved whole across an update: install.sh copies
the live file aside and restores it over the freshly shipped template. That is
the right call for a file holding the Slack webhook and tuned thresholds, but
it also means a default introduced or changed after a host's first install
never reaches that host. ``thresholds.system.disk_usage_*`` is the case that
surfaced it -- hosts installed before the web disk warning bar still carried
80/90 while the shipped file had moved to 85/95.

A value on its own cannot say whether ``90`` is a deliberate choice or an
untouched default, so this module records what LLDPq itself last shipped for
each managed key. Every later update resolves a key to one of three states:

    absent from the file      -> write the shipped value
    equal to the record       -> untouched, adopt the newly shipped value
    different from the record -> the operator owns it, leave it alone

Ownership is sticky. Once a difference is seen the key is marked and stays
marked, so a shipped default that later happens to match the operator's value
cannot quietly reclaim it. Nothing has to be threaded through the web write
paths for this: a change made in Setup shows up as a difference on the next
update and marks the key from there on.

Two limits are deliberate. A host that predates the record has no base to
compare against, so the first run treats a value as untouched only when it
matches one of the values LLDPq is known to have shipped for that key
(HISTORICAL_DEFAULTS); an operator who had independently chosen exactly that
number is indistinguishable and will be moved once. And only scalar leaves are
managed -- lists like ``alert_strategy.summary_times`` carry order and intent
that a key-wise merge cannot reason about.
"""

from __future__ import annotations

import argparse
import fcntl
import io
import json
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import yaml

STATE_VERSION = 1
DEFAULT_STATE_PATH = "/var/lib/lldpq/config-provenance.json"

# Sections whose scalar leaves are LLDPq defaults. Naming sections rather than
# individual keys is the point of the feature: a threshold added in a later
# release is covered without touching this file.
MANAGED_SECTIONS: Tuple[str, ...] = (
    "thresholds",
    "frequency",
    "alert_types",
    "alert_strategy",
    "templates",
)

# Never managed, even if a section above is widened later.
#   notifications.*            -> master switch, server URL, and Slack secrets;
#                                 host-specific or operator identity
#   alert_strategy list fields -> ordered operator intent, not a scalar default
EXCLUDED_PATHS = frozenset({
    "notifications",
    "alert_strategy.summary_times",
    "alert_strategy.always_immediate",
})

# Values LLDPq shipped for a key before the current release. Used only to seed
# a host that has no record yet, so an untouched old default can be recognised.
HISTORICAL_DEFAULTS: Dict[str, Tuple[Any, ...]] = {
    "thresholds.system.disk_usage_warning": (80,),
    "thresholds.system.disk_usage_critical": (90,),
}

SCALAR_TYPES = (bool, int, float, str)


class ProvenanceError(Exception):
    """A condition that must abort the merge with the file left untouched."""


def _is_scalar(value: Any) -> bool:
    # None is excluded on purpose: an explicitly blanked value is a choice, and
    # replacing it with a shipped default would undo that.
    return isinstance(value, SCALAR_TYPES)


def _managed_paths(shipped: Dict[str, Any]) -> List[str]:
    """Dotted paths of every managed scalar leaf in the shipped template."""
    found: List[str] = []

    def walk(node: Any, prefix: str) -> None:
        if prefix in EXCLUDED_PATHS:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(key, str):
                    continue
                walk(value, f"{prefix}.{key}" if prefix else key)
        elif _is_scalar(node) and prefix:
            found.append(prefix)

    for section in MANAGED_SECTIONS:
        if section in EXCLUDED_PATHS:
            continue
        if section in shipped:
            walk(shipped[section], section)
    return found


def _dig(node: Any, path: str) -> Tuple[bool, Any]:
    """(found, value) for a dotted path."""
    current = node
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _plant(node: Any, path: str, value: Any) -> None:
    """Set a dotted path, creating intermediate mappings as needed."""
    parts = path.split(".")
    current = node
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _plain(value: Any) -> Any:
    """Reduce a ruamel scalar to the plain type, so the JSON record stays a
    record and not a pickle of the loader's formatting objects."""
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    return value


def _same(left: Any, right: Any) -> bool:
    """Compare as configuration values, not as Python objects.

    A round-tripped YAML scalar can come back as a subclass (ruamel keeps
    formatting on ints and floats), and ``1`` must not equal ``True``.
    """
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return left == right


def load_state(path: str) -> Dict[str, Any]:
    try:
        with open(path) as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {"version": STATE_VERSION, "files": {}}
    except (OSError, ValueError):
        # An unreadable record must not hand every key to the shipped default;
        # rebuilding from scratch re-derives ownership from HISTORICAL_DEFAULTS.
        return {"version": STATE_VERSION, "files": {}}
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        return {"version": STATE_VERSION, "files": {}}
    if not isinstance(state.get("files"), dict):
        state["files"] = {}
    return state


def save_state(path: str, state: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", dir=directory, prefix=".config-provenance.", delete=False
    )
    try:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.chmod(handle.name, 0o600)
        os.replace(handle.name, path)
    except Exception:
        os.unlink(handle.name)
        raise


def _atomic_write_preserving_identity(path: str, text: str) -> None:
    """Replace *path* with *text*, keeping its mode and ownership.

    A plain tempfile+rename hands the file the temp file's 0600/root identity.
    notifications.yaml is read by www-data through Setup and by the disk status
    endpoint, so losing the ``$LLDPQ_USER:www-data`` 664 pattern silently
    breaks both.
    """
    original = os.stat(path)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    handle = tempfile.NamedTemporaryFile(
        "w", dir=directory, prefix=".notifications.", delete=False
    )
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.chmod(handle.name, original.st_mode & 0o7777)
        try:
            os.chown(handle.name, original.st_uid, original.st_gid)
        except PermissionError:
            # Unprivileged runs (tests) cannot chown; the mode still carries.
            pass
        os.replace(handle.name, path)
    except Exception:
        if os.path.exists(handle.name):
            os.unlink(handle.name)
        raise


def _roundtrip_loader():
    try:
        from ruamel.yaml import YAML
    except ImportError as exc:
        raise ProvenanceError(
            "ruamel.yaml is unavailable; refusing to rewrite notifications.yaml "
            "because a plain YAML dump would strip every comment"
        ) from exc
    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    # notifications.yaml indents sequence items under their key (dash at +2,
    # content at +4). ruamel's default would re-indent every list in the file,
    # producing a diff in sections this module promises not to manage.
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    # The shipped file has lines past 80 columns (threshold comments); rewrapping
    # them would be another unrequested diff.
    yaml_rt.width = 4096
    return yaml_rt


def _load_roundtrip(path: str, label: str = "notifications.yaml"):
    """Load *path* with ruamel so comments, key order, and -- just as important
    -- scalar resolution match on both sides of the comparison.

    Both files must go through the same loader. PyYAML follows YAML 1.1, where
    ``1e-12`` is a string because the exponent form needs a decimal point,
    while ruamel follows YAML 1.2 and reads it as a float. Mixing the two made
    ``thresholds.network.ber_error_rate`` compare unequal to itself and get
    frozen as an operator value on every host.
    """
    yaml_rt = _roundtrip_loader()
    with open(path) as handle:
        loaded = yaml_rt.load(handle)
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ProvenanceError(f"{label} must contain a mapping")
    return yaml_rt, loaded


def merge(
    target: str,
    shipped_path: str,
    state_path: str = DEFAULT_STATE_PATH,
    lock_path: Optional[str] = None,
    apply_changes: bool = True,
) -> List[str]:
    """Reconcile *target* against *shipped_path*; return one line per decision.

    The file is only rewritten when a managed key actually changes, and only
    after the rendered result has been parsed back successfully.
    """
    if not os.path.isfile(target):
        # Creating the file is install.sh's job; nothing to reconcile.
        return []
    # Docker points this path at a mounted config directory. Writing through the
    # link keeps the operator's file persistent; replacing the path itself would
    # leave a regular file in the image layer and silently drop persistence.
    target = os.path.realpath(target)
    _, shipped = _load_roundtrip(shipped_path, "shipped notifications.yaml")

    lock_handle = None
    if lock_path and os.path.exists(lock_path):
        # Written without the shared lock a concurrent Setup save could be lost,
        # so a lock that cannot be taken aborts rather than proceeding bare.
        lock_handle = open(lock_path, "r+")
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lock_handle.close()
            raise ProvenanceError(
                "another writer holds the LLDPq configuration lock"
            ) from exc

    try:
        yaml_rt, current = _load_roundtrip(target)
        with open(target) as handle:
            original = yaml.safe_load(handle) or {}
        state = load_state(state_path)
        file_state = state["files"].setdefault(
            os.path.basename(target), {"keys": {}}
        )
        if not isinstance(file_state.get("keys"), dict):
            file_state["keys"] = {}
        keys = file_state["keys"]

        report: List[str] = []
        changed = False

        for path in _managed_paths(shipped):
            _, shipped_value = _dig(shipped, path)
            present, live_value = _dig(current, path)
            record = keys.get(path)
            if not isinstance(record, dict):
                record = None

            if not present:
                _plant(current, path, shipped_value)
                keys[path] = {"shipped": _plain(shipped_value), "operator_owned": False}
                changed = True
                report.append(f"added {path} = {shipped_value!r}")
                continue

            if record is not None and record.get("operator_owned"):
                # Keep the record's base current so it always says what LLDPq
                # last shipped, without ever reclaiming the key.
                keys[path] = {"shipped": _plain(shipped_value), "operator_owned": True}
                continue

            if record is not None:
                base_values: Tuple[Any, ...] = (record.get("shipped"),)
            else:
                # No record: a value counts as untouched only if LLDPq is known
                # to have shipped it.
                base_values = HISTORICAL_DEFAULTS.get(path, ()) + (shipped_value,)

            if any(_same(live_value, base) for base in base_values):
                if not _same(live_value, shipped_value):
                    _plant(current, path, shipped_value)
                    changed = True
                    report.append(
                        f"adopted {path}: {live_value!r} -> {shipped_value!r}"
                    )
                keys[path] = {"shipped": _plain(shipped_value), "operator_owned": False}
            else:
                keys[path] = {"shipped": _plain(shipped_value), "operator_owned": True}
                report.append(f"kept {path} = {live_value!r} (operator value)")

        if not apply_changes:
            return report

        if changed:
            buffer = io.StringIO()
            yaml_rt.dump(current, buffer)
            rendered = buffer.getvalue()
            # Never publish something that cannot be read back, and prove the
            # Slack section came through untouched before replacing the file.
            verify = yaml.safe_load(rendered)
            if not isinstance(verify, dict):
                raise ProvenanceError("merged notifications.yaml did not parse back")
            if verify.get("notifications") != original.get("notifications"):
                raise ProvenanceError(
                    "merge would have modified the notifications section; aborted"
                )
            _atomic_write_preserving_identity(target, rendered)

        save_state(state_path, state)
        return report
    finally:
        if lock_handle is not None:
            lock_handle.close()


def seed(
    target: str,
    shipped_path: str,
    state_path: str = DEFAULT_STATE_PATH,
) -> List[str]:
    """Record the shipped defaults for a fresh install without touching files.

    A fresh install already has the shipped file, so there is nothing to merge;
    writing the record now gives the next update an exact base instead of
    falling back to HISTORICAL_DEFAULTS.
    """
    _, shipped = _load_roundtrip(shipped_path, "shipped notifications.yaml")
    state = load_state(state_path)
    file_state = state["files"].setdefault(os.path.basename(target), {"keys": {}})
    file_state["keys"] = {
        path: {"shipped": _plain(_dig(shipped, path)[1]), "operator_owned": False}
        for path in _managed_paths(shipped)
    }
    save_state(state_path, state)
    return [f"recorded {len(file_state['keys'])} shipped defaults"]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile notifications.yaml with newly shipped defaults"
    )
    parser.add_argument("action", choices=("merge", "seed"))
    parser.add_argument("--target", required=True)
    parser.add_argument("--shipped", required=True)
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--lock", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.action == "seed":
            report = seed(args.target, args.shipped, args.state)
        else:
            report = merge(
                args.target,
                args.shipped,
                args.state,
                lock_path=args.lock,
                apply_changes=not args.dry_run,
            )
    except ProvenanceError as exc:
        # Non-fatal for the installer: the operator's file is untouched and the
        # only cost is that a new default waits for the next update.
        print(f"notifications.yaml defaults not reconciled: {exc}", file=sys.stderr)
        return 0
    except Exception as exc:  # pragma: no cover - defensive
        print(f"notifications.yaml defaults not reconciled: {exc}", file=sys.stderr)
        return 0

    for line in report:
        print(f"    • {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
