# Source this file from any cloned consumer repository.
_GHA_SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/dispatch.py"
gha_setup() { python3 "$_GHA_SCRIPT" setup "$@"; }
gha_run() { python3 "$_GHA_SCRIPT" run "$@"; }
gha_plan() { python3 "$_GHA_SCRIPT" plan "$@"; }
gha_apply() { python3 "$_GHA_SCRIPT" apply "$@"; }
gha_runs() { python3 "$_GHA_SCRIPT" runs "$@"; }
gha_watch() { python3 "$_GHA_SCRIPT" watch "$@"; }
gha_view() { python3 "$_GHA_SCRIPT" view "$@"; }
gha_plan_watch() { python3 "$_GHA_SCRIPT" plan-watch "$@"; }
gha_latest() { python3 "$_GHA_SCRIPT" latest "$@"; }
gha_open() { python3 "$_GHA_SCRIPT" open "$@"; }
