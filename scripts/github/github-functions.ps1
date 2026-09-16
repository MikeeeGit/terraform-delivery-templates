# Dot-source; Python 3 and GitHub CLI must be on PATH.
$Script:GitHubDeliveryScript = Join-Path $PSScriptRoot 'dispatch.py'
function Invoke-GhDelivery {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    & python3 $Script:GitHubDeliveryScript @Arguments
    if ($LASTEXITCODE -ne 0) { throw "GitHub operation stopped (exit $LASTEXITCODE)." }
}
function gha_setup { Invoke-GhDelivery setup @args }
function gha_run { Invoke-GhDelivery run @args }
function gha_plan { Invoke-GhDelivery plan @args }
function gha_apply { Invoke-GhDelivery apply @args }
function gha_runs { Invoke-GhDelivery runs @args }
function gha_watch { Invoke-GhDelivery watch @args }
function gha_view { Invoke-GhDelivery view @args }
function gha_plan_watch { Invoke-GhDelivery plan-watch @args }
function gha_latest { Invoke-GhDelivery latest @args }
function gha_open { Invoke-GhDelivery open @args }
