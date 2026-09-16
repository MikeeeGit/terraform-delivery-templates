# Dot-source this file. Python 3 is the shared, tested execution boundary.
$Script:TerraformDeliveryScript = Join-Path $PSScriptRoot 'terraform.py'
function Invoke-TfDelivery {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    & python3 $Script:TerraformDeliveryScript @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Terraform operation stopped (exit $LASTEXITCODE)." }
}
function tf_setup {
    param([Parameter(Mandatory=$true)][string]$RepoName,
          [Parameter(Mandatory=$true)][string]$Environment,
          [Parameter(Mandatory=$true)][string]$Location,
          [string]$CustomerPrefix)
    $parameters = @('setup','--repository',$RepoName,'--environment',$Environment,'--region',$Location)
    if ($CustomerPrefix) { $parameters += @('--prefix',$CustomerPrefix) }
    Invoke-TfDelivery @parameters
}
function tf_init { Invoke-TfDelivery init @args }
function tf_plan { Invoke-TfDelivery plan @args }
function tf_apply { Invoke-TfDelivery apply @args }
function tf_destroy { Invoke-TfDelivery destroy @args }
function tf_import { Invoke-TfDelivery import @args }
function tf_env { Invoke-TfDelivery env }
function tf_upgrade { Invoke-TfDelivery init --upgrade }
function tf_deploy { tf_setup @args; tf_init; tf_plan; tf_apply }
function az_sub { az account show --query '{Name:name,IsDefault:isDefault}' -o table }
