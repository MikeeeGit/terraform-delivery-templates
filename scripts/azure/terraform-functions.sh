#!/usr/bin/env bash
# Source this file; operations execute in the caller's repository.
_TF_DELIVERY_SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/terraform.py"
tf_setup() {
  if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then echo 'Usage: tf_setup <repository> <environment> <region> [prefix]' >&2; return 2; fi
  local args=(setup --repository "$1" --environment "$2" --region "$3")
  if [ "$#" -eq 4 ]; then args+=(--prefix "$4"); fi
  python3 "$_TF_DELIVERY_SCRIPT" "${args[@]}"
}
tf_init() { python3 "$_TF_DELIVERY_SCRIPT" init "$@"; }
tf_plan() { python3 "$_TF_DELIVERY_SCRIPT" plan "$@"; }
tf_apply() { python3 "$_TF_DELIVERY_SCRIPT" apply "$@"; }
tf_destroy() { python3 "$_TF_DELIVERY_SCRIPT" destroy "$@"; }
tf_import() { python3 "$_TF_DELIVERY_SCRIPT" import "$@"; }
tf_env() { python3 "$_TF_DELIVERY_SCRIPT" env; }
tf_upgrade() { python3 "$_TF_DELIVERY_SCRIPT" init --upgrade; }
tf_deploy() { tf_setup "$@" && tf_init && tf_plan && tf_apply; }
az_sub() { az account show --query '{Name:name,IsDefault:isDefault}' -o table; }
