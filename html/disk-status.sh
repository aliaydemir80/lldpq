#!/bin/bash
# disk-status.sh — host filesystem headroom for the shell's disk warning bar.
# Called by nginx via fcgiwrap.
#
# Deliberately cheap: df only, no du and no sudo, because index.html polls this
# on a timer for every logged-in session. Setup's get-maintenance action stays
# the place for the expensive per-directory accounting.

source "$(dirname "$0")/auth-guard.sh"
require_auth   # a filling disk breaks collection for operators too, not just admins

echo "Content-Type: application/json"
echo "Cache-Control: no-store, no-cache, must-revalidate, max-age=0"
echo "Pragma: no-cache"
echo "Expires: 0"
echo "X-Content-Type-Options: nosniff"
echo ""

# Load allowlisted config data through the fixed, root-owned parser. A missing
# helper is a broken/partial installation; guessing paths would measure the
# wrong filesystem and warn about a disk the installation does not use.
if [[ ! -x /usr/local/bin/lldpq-config ]]; then
    echo '{"success": false, "error": "Required runtime config helper is missing; run install.sh to repair this installation."}'
    exit 0
fi
if ! LLDPQ_CONFIG_ASSIGNMENTS=$(/usr/local/bin/lldpq-config --require-config \
    --require-key LLDPQ_DIR --require-key WEB_ROOT 2>/dev/null); then
    echo '{"success": false, "error": "Runtime configuration is missing or unreadable; run install.sh to repair this installation."}'
    exit 0
fi
eval "$LLDPQ_CONFIG_ASSIGNMENTS"

export LLDPQ_DIR="${LLDPQ_DIR:-/home/lldpq/lldpq}"
export WEB_ROOT="${WEB_ROOT:-/var/www/html}"

python3 <<'PYEOF'
import json
import os
import subprocess

# Used when notifications.yaml is absent or carries an unusable value. The
# warning tier has to sit far enough below critical that there is still time to
# reclaim space before collection starts failing.
DEFAULT_WARNING = 85
DEFAULT_CRITICAL = 95

lldpq_dir = os.environ.get('LLDPQ_DIR', '/home/lldpq/lldpq')
web_root = os.environ.get('WEB_ROOT', '/var/www/html')


def _threshold(raw, fallback):
    """Coerce a configured percentage, falling back on anything unusable."""
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return fallback
    if not 1 <= value <= 100:
        return fallback
    return value


def read_thresholds():
    """Percentages from notifications.yaml, which Setup step 7 already edits.

    notifications.enabled is deliberately ignored: that flag governs Slack
    delivery, and a filling disk still has to reach the operator looking at
    the UI when outbound alerting is switched off.
    """
    warning, critical = DEFAULT_WARNING, DEFAULT_CRITICAL
    path = os.path.join(lldpq_dir, 'notifications.yaml')
    try:
        import yaml
        with open(path) as fh:
            cfg = yaml.safe_load(fh) or {}
        if isinstance(cfg, dict):
            thresholds = cfg.get('thresholds')
            system = thresholds.get('system') if isinstance(thresholds, dict) else None
            if isinstance(system, dict):
                warning = _threshold(system.get('disk_usage_warning'), warning)
                critical = _threshold(system.get('disk_usage_critical'), critical)
    except Exception:
        pass
    # An inverted pair would leave the warning tier unreachable and report a
    # full disk as merely "ok" right up to the critical edge.
    if warning > critical:
        warning = critical
    return warning, critical


def probe(path):
    """One df -Pk record for *path*, or None when the probe cannot answer.

    -Pk pins POSIX single-line output in 1024-byte blocks, matching how
    monitor.sh already measures publish headroom.
    """
    try:
        result = subprocess.run(['df', '-Pk', '--', path],
                                capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    # Mount points may contain spaces, so the trailing field absorbs the rest.
    fields = lines[-1].split(None, 5)
    if len(fields) < 6:
        return None
    try:
        total_kb = int(fields[1])
        used_kb = int(fields[2])
        avail_kb = int(fields[3])
    except ValueError:
        return None
    percent = _threshold(fields[4].rstrip('%'), None)
    if percent is None:
        # tmpfs and some overlays leave the capacity column unusable; derive it
        # from the blocks actually accounted for rather than dropping the mount.
        denominator = used_kb + avail_kb
        if denominator <= 0:
            return None
        percent = int(round(used_kb * 100.0 / denominator))
    if total_kb <= 0:
        return None
    return {
        'mount': fields[5],
        'percent': percent,
        'avail_mb': avail_kb // 1024,
        'total_mb': total_kb // 1024,
    }


warning, critical = read_thresholds()

# The three paths that matter to this installation. They frequently share one
# filesystem, so entries collapse by mount point: reporting the same disk three
# times would read as three separate problems.
mounts = []
by_mount = {}
for path in (lldpq_dir, web_root, '/'):
    record = probe(path)
    if record is None:
        continue
    existing = by_mount.get(record['mount'])
    if existing is not None:
        if path not in existing['paths']:
            existing['paths'].append(path)
        continue
    record['paths'] = [path]
    by_mount[record['mount']] = record
    mounts.append(record)

mounts.sort(key=lambda record: record['percent'], reverse=True)

if not mounts:
    # No invented percentage: a dead probe is reported as unknown so the UI can
    # stay silent instead of implying a healthy disk.
    level = 'unknown'
    worst = None
else:
    worst = mounts[0]['percent']
    if worst >= critical:
        level = 'critical'
    elif worst >= warning:
        level = 'warning'
    else:
        level = 'ok'

print(json.dumps({
    'success': True,
    'level': level,
    'worst_percent': worst,
    'thresholds': {'warning': warning, 'critical': critical},
    'mounts': mounts,
}))
PYEOF
