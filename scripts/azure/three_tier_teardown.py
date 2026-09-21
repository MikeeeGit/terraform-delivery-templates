#!/usr/bin/env python3
"""Guarded disposable three-tier lab removal: inventory, saved plans and exact-plan apply."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

# Inert synthetic defaults support offline tests. The CLI always requires a
# reviewed private configuration before accessing a real workspace or account.
BASE = Path("/configure/workspace")
PRIVATE = Path("/configure/private-evidence")
PROFILE = Path("/configure/operator-azure")
PAT_FILE = Path("/configure/bootstrap.pat")
TERRAFORM = Path("/configure/terraform")
SUBSCRIPTION = "00000000-0000-0000-0000-000000000002"
TENANT = "00000000-0000-0000-0000-000000000001"
PROJECT = "00000000-0000-0000-0000-000000000003"
PROTECTED_ADMIN_GROUP = "00000000-0000-0000-0000-000000000004"
ORGANIZATION = "https://dev.azure.com/example/"
STORAGE_PREFIX = "example"
TARGETS = {
    'aks-lab-gateway': ('pprd',),
    'aks-lab-aks': ('pprd',),
    'aks-lab-workload-vault': ('pprd',),
    'aks-lab-routes': ('hub',),
    'aks-lab-firewall': ('hub',),
    'aks-lab-private-worker': ('hub',),
    'aks-lab-network': ('hub', 'pprd', 'prd'),
    'aks-lab-azure-devops-connections': ('hub', 'pprd', 'prd'),
    'aks-lab-delivery-identities': ('hub', 'pprd', 'prd'),
}
CONNECTIONS = 'aks-lab-azure-devops-connections'
IDENTITIES = 'aks-lab-delivery-identities'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def comparable_state(state):
    """Ignore only Terraform's unordered check-result serialization.

    Resource instances, values, lineage and serial remain exact comparisons.
    Terraform state pull can reorder check objects without changing the blob.
    """
    result = json.loads(json.dumps(state))
    checks = result.get("check_results")
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check.get("objects"), list):
                check["objects"].sort(key=lambda item: json.dumps(item, sort_keys=True))
        checks.sort(key=lambda item: json.dumps(item, sort_keys=True))
    return result


def regular(path):
    require(not path.is_symlink() and path.is_file(), 'Expected a regular, non-symlink input: ' + str(path))
    return path.read_bytes()


def private_path(path, directory=False):
    info = path.lstat()
    require(not path.is_symlink() and info.st_uid == os.getuid(), 'Private path must be owned by the operator')
    require(stat.S_IMODE(info.st_mode) & 0o077 == 0, 'Private path must have no group/other access')
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), 'Unexpected private path type')


def expected_backend(component, environment):
    require(environment in TARGETS.get(component, ()), 'Component/environment is not whitelisted; bootstrap-state is excluded')
    backend_environment = 'hub' if component in (CONNECTIONS, IDENTITIES) else environment
    return {
        'resource_group_name': f'uks-{backend_environment}-aks-lab-tfstate-rsg',
        'storage_account_name': f'uks{backend_environment}{STORAGE_PREFIX}tfstatesa',
        'container_name': 'aks-lab-bootstrap' if component in (CONNECTIONS, IDENTITIES) else f'uks-{environment}-azdo-tfstate',
        'key': f'{component}-{environment}-uks.tfstate',
        'subscription_id': SUBSCRIPTION,
        'tenant_id': TENANT,
        'use_azuread_auth': True,
    }


def read_simple_backend(path):
    result = {}
    for line in regular(path).decode().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([a-z_]+)\s*=\s*("[^"\n]*"|true|false)', line)
        require(match is not None, 'Unexpected backend syntax')
        require(match[1] not in result, 'Duplicate backend setting')
        result[match[1]] = json.loads(match[2])
    return result


def check_delivery(root, component, environment, backend):
    if component == CONNECTIONS:
        name = 'backend.hcl' if environment == 'hub' else f'backend-{environment}.hcl'
        require(read_simple_backend(root / name) == backend, 'Connection backend differs from exact approved target')
        return name
    config = json.loads(regular(root / 'delivery.azure.json'))
    require(config['tenant_id'] == TENANT and config['prefix'] == STORAGE_PREFIX, 'Delivery tenant/prefix mismatch')
    require(config['regions'] == ['uks'] and config['secondary_region'] == 'uks', 'Delivery region mismatch')
    require(config['subscriptions'] and set(config['subscriptions'].values()) == {SUBSCRIPTION}, 'Every subscription alias must select disposable PPRD')
    selected = config['environments'][environment]
    require(selected == {'subscription_alias': environment, 'backend_environment': environment}, 'Environment alias mismatch')
    require(config['backend']['subscription_alias'] == 'hub', 'Backend subscription alias mismatch')
    fields = dict(secondary_region='uks', backend_environment=environment, prefix=STORAGE_PREFIX, repository=component, environment=environment, region='uks')
    for source, target in [('resource_group', 'resource_group_name'), ('storage_account', 'storage_account_name'), ('container', 'container_name'), ('key', 'key')]:
        require(config['backend'][source].format(**fields) == backend[target], 'Delivery backend differs from exact approved target: ' + target)
    return 'delivery.azure.json'


def validate_variables(values, component, environment):
    """Check effective values from the plan JSON, or selected connection JSON."""
    if component == CONNECTIONS:
        require(values.get('identity_subscription_id') == SUBSCRIPTION and values.get('tenant_id') == TENANT, 'Connection identity target mismatch')
        require(values.get('project_id') == PROJECT and values.get('organization_url') == ORGANIZATION, 'Connection project/organization mismatch')
        connections = values.get('connections', {})
        require(bool(connections), 'No authorized connections in selected environment')
        for name, entry in connections.items():
            require(name.startswith(environment + '-'), 'Connection belongs to a different environment')
            require(entry['target_subscription_id'] == SUBSCRIPTION, 'Connection target subscription mismatch')
            prefix = f'/subscriptions/{SUBSCRIPTION}/resourceGroups/uks-{environment}-aks-lab-'
            require(entry['identity_id'].startswith(prefix), 'Connection identity scope mismatch')
        return
    expected = {}
    if component != 'aks-lab-private-worker':
        expected['environment'] = environment
    if component in ('aks-lab-network', 'aks-lab-firewall', 'aks-lab-aks', 'aks-lab-gateway'):
        expected.update(subscription=environment, location_abbreviated='uks')
        require(set(values.get('subscription_id_map', {}).values()) == {SUBSCRIPTION}, 'Subscription map escapes disposable PPRD')
    if component in ('aks-lab-workload-vault', IDENTITIES):
        expected.update(region='uks', subscription_id=SUBSCRIPTION)
    if component == 'aks-lab-private-worker':
        expected.update(subscription_id=SUBSCRIPTION, name_prefix='uks-hub-aks-lab-worker')
    if component != 'aks-lab-network':
        expected['tenant_id'] = TENANT
    if component == 'aks-lab-routes':
        expected['location_abbreviated'] = 'uks'
        for slot in ('pprd', 'prd'):
            require(values.get(slot, {}).get('subscription_id') == SUBSCRIPTION, 'Route subscription mismatch')
    for key, value in expected.items():
        require(values.get(key) == value, 'Effective plan input mismatch: ' + key)


def include_file_dependencies(root, selected, component, variable_files):
    """Copy literal file/template dependencies; reject unsupported dynamic paths offline."""
    dependencies = set()
    dynamic_waf = {
        '${local.waf_config_root}/${policy.files.rule_group_overrides}',
        '${local.waf_config_root}/${policy.files.managed_rule_exclusions}',
        '${local.waf_config_root}/${policy.files.custom_rules}',
        '${local.waf_config_root}/${filename}',
    }
    for name in sorted(selected):
        if not name.endswith('.tf'):
            continue
        text = regular(root / name).decode()
        calls = list(re.finditer(r'\b(file|filebase64|templatefile|filesha256|filebase64sha256|fileexists|fileset)\s*\(\s*', text))
        for call in calls:
            argument = re.match(r'"([^"\n]*)"', text[call.end():])
            require(argument is not None, 'Unreviewed non-literal file dependency in ' + name)
            value = argument[1]
            if component == 'aks-lab-gateway' and name == 'waf.tf' and value in dynamic_waf:
                require('coalesce(var.waf_config_root, "${path.root}/config/all/waf-policy")' in text, 'Gateway file root needs explicit dependency review')
                for var_file in variable_files:
                    variables = regular(root / var_file).decode()
                    if var_file.endswith('.json'):
                        require(json.loads(variables).get('waf_config_root') is None, 'Custom WAF file root needs explicit dependency review')
                    else:
                        require(all(value.strip() == 'null' for value in re.findall(r'^\s*waf_config_root\s*=\s*([^\n]+)', variables, re.M)), 'Custom WAF file root needs explicit dependency review')
                    for filename in re.findall(r'(?:rule_group_overrides|managed_rule_exclusions|custom_rules)\s*[=:]\s*"([^"\n]+)"', variables):
                        path = root / 'config/all/waf-policy' / filename
                        require(path.resolve().is_relative_to(root.resolve()), 'WAF file escapes source root')
                        regular(path)
                        dependencies.add(str(path.relative_to(root)))
                continue
            value = value.replace('${path.root}', str(root)).replace('${path.module}', str((root / name).parent))
            require('${' not in value, 'Unreviewed dynamic file dependency in ' + name)
            path = Path(value) if Path(value).is_absolute() else root / value
            require(path.resolve().is_relative_to(root.resolve()), 'File dependency escapes source root')
            if call[1] == 'fileset':
                require(path.is_dir() and not path.is_symlink(), 'Missing fileset directory')
                paths = [p for p in path.rglob('*') if p.is_file()]
            else:
                paths = [path]
            for path in paths:
                regular(path)
                for ancestor in path.parents:
                    if ancestor == root:
                        break
                    require(not ancestor.is_symlink(), 'Symlink in file dependency')
                dependencies.add(str(path.relative_to(root)))
    selected.update(dependencies)
    return sorted(dependencies)


def inventory(component, environment, base=None):
    base = BASE if base is None else base
    backend = expected_backend(component, environment)
    root = base / component
    require(root.resolve().parent == base.resolve() and not root.is_symlink(), 'Root escapes private lab')
    config_file = check_delivery(root, component, environment, backend)
    variables = [f'{environment}.authorized.tfvars.json'] if component == CONNECTIONS else ['config/global.tfvars', f'config/uks/{environment}/{environment}.tfvars']
    for name in variables:
        regular(root / name)
    if component == CONNECTIONS:
        validate_variables(json.loads(regular(root / variables[0])), component, environment)
        override = regular(root / 'azuredevops-auth_override.tf').decode()
        require(re.search(r'use_cli\s*=\s*false', override) is not None, 'Reviewed PAT-only provider override is missing')
    else:
        text = regular(root / variables[-1]).decode()
        if component != 'aks-lab-private-worker':
            require(re.search(r'^\s*environment\s*=\s*"' + environment + '"\s*$', text, re.M) is not None, 'Selected var file environment mismatch')
    selected = set(variables + [config_file, '.terraform.lock.hcl'])
    # Include ignored generated providers and implicit variables, not just Git-tracked files.
    for file in root.iterdir():
        if file.name.endswith(('.tf', '.tf.json', '.auto.tfvars', '.auto.tfvars.json')) or file.name in ('terraform.tfvars', 'terraform.tfvars.json'):
            selected.add(file.name)
    for folder in ('config', 'modules'):
        if (root / folder).exists():
            require(not (root / folder).is_symlink(), 'Selected source directory is a symlink')
            for file in (root / folder).rglob('*'):
                if any(part in ('.terraform', '.git', '.delivery', '.terraform-delivery', '__pycache__') for part in file.relative_to(root).parts):
                    continue
                require(not file.is_symlink(), 'Symlink in selected source tree')
                if file.is_file():
                    selected.add(str(file.relative_to(root)))
    implicit = [name for name in selected if name.endswith(('.auto.tfvars', '.auto.tfvars.json')) or name in ('terraform.tfvars', 'terraform.tfvars.json')]
    dependencies = include_file_dependencies(root, selected, component, variables + implicit)
    files = {name: digest(regular(root / name)) for name in sorted(selected)}
    for name in files:
        require('..' not in Path(name).parts and not Path(name).is_absolute(), 'Unsafe source path')
        if name.endswith(('.tf', '.tf.json')):
            text = regular(root / name).decode()
            require(re.search(r'\bprovisioner\s+"|\bdata\s+"external"', text) is None, 'Planner does not accept provisioners/external execution')
    binding = {'component': component, 'environment': environment, 'region': 'uks', 'backend': backend, 'var_files': variables, 'implicit_var_files': sorted(implicit), 'file_dependencies': dependencies, 'files': files}
    return dict(binding, source_sha256=digest(json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()))


def child_environment(directory, inherited=None):
    original = os.environ if inherited is None else inherited
    clean = {key: value for key, value in original.items() if not key.startswith(('ARM_', 'AZURE_', 'AZDO_', 'TF_', 'MSI_', 'IDENTITY_', 'ACTIONS_ID_TOKEN_', 'SYSTEM_ACCESSTOKEN'))}
    clean.update(AZURE_CONFIG_DIR=str(PROFILE), AZURE_CORE_ONLY_SHOW_ERRORS='true', ARM_USE_CLI='true', ARM_USE_OIDC='false', ARM_USE_MSI='false', ARM_USE_AZUREAD='true', ARM_TENANT_ID=TENANT, ARM_SUBSCRIPTION_ID=SUBSCRIPTION, ARM_RESOURCE_PROVIDER_REGISTRATIONS='none', TF_IN_AUTOMATION='1', TF_INPUT='0', TF_WORKSPACE='default', TF_DATA_DIR=str(directory / 'terraform-data'))
    return clean


def create_output(path, private=None):
    private = PRIVATE if private is None else private
    require(path.is_absolute() and path.parent.resolve().is_relative_to(private.resolve()), 'Output must be below the private non-Git workspace')
    for ancestor in [path, *path.parents]:
        require(not ancestor.is_symlink(), 'Output has a symlink ancestor')
        require(not (ancestor / '.git').exists(), 'Private output cannot be inside a Git tree')
    private_path(private, directory=True)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_path(path.parent, directory=True)
    path.mkdir(mode=0o700, exist_ok=False)


def write_private(path, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data if isinstance(data, bytes) else data.encode())


def run(command, cwd, env, stage, allowed=(0,)):
    # Never print command output or save raw subprocess diagnostics: providers may echo private values.
    result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(result.returncode in allowed, f'{stage} failed (exit {result.returncode}); no resource apply was attempted')
    return result.stdout


def blob_metadata(backend, work, env, destination):
    command = ['az', 'storage', 'blob', 'show', '--account-name', backend['storage_account_name'], '--container-name', backend['container_name'], '--name', backend['key'], '--auth-mode', 'login', '--subscription', SUBSCRIPTION, '--output', 'json']
    metadata = json.loads(run(command, work, env, 'State Blob metadata capture'))
    require(metadata.get('name') == backend['key'], 'Blob metadata belongs to another state key')
    write_private(destination, json.dumps(metadata, indent=2) + '\n')
    return metadata


def preserve_failed_plan(backend, work, env, output, component, environment):
    """Read-only evidence for exact-lease recovery, which remains a separate operation."""
    evidence = {'status': 'plan-failed-do-not-apply', 'automatic_unlock_attempted': False, 'resource_apply_performed': False}
    try:
        blob_metadata(backend, work, env, output / 'blob-after-failure.json')
        evidence['blob_metadata_saved'] = True
    except (ValueError, OSError, KeyError):
        evidence['blob_metadata_saved'] = False
    try:
        snapshot = run([str(TERRAFORM), 'state', 'pull'], work, env, 'Failure-state snapshot')
        validate_state(json.loads(snapshot), component, environment)
        write_private(output / 'state-after-failure.tfstate', snapshot)
        evidence['state_snapshot_saved'] = True
    except (ValueError, OSError, KeyError):
        evidence['state_snapshot_saved'] = False
    write_private(output / 'failure.json', json.dumps(evidence, indent=2) + '\n')


def validate_backend_cache(cache, expected):
    backend = cache.get('backend', {})
    require(backend.get('type') == 'azurerm', 'Unexpected initialized backend type')
    actual = backend.get('config', {})
    for key, value in expected.items():
        require(actual.get(key) == value, 'Initialized backend mismatch: ' + key)
    require(actual.get('use_cli') is True and not actual.get('use_oidc') and not actual.get('use_msi'), 'Backend is not using isolated operator CLI authentication')
    for key in ('access_key', 'sas_token', 'client_secret', 'client_certificate_path', 'client_certificate_password', 'oidc_token', 'oidc_token_file_path'):
        require(not actual.get(key), 'Unexpected alternative backend credential')


def resource_groups(component, environment):
    own = {
        'aks-lab-gateway': {'uks-pprd-aks-lab-appgateway-rg'},
        'aks-lab-aks': {'uks-pprd-akslab-aks-rg'},
        'aks-lab-workload-vault': {'uks-pprd-aks-lab-vault-rg'},
        'aks-lab-routes': {'uks-pprd-aks-lab-vnet-rg-01', 'uks-prd-aks-lab-vnet-rg-01'},
        'aks-lab-firewall': {'uks-hub-aks-lab-vnet-rg-01'},
        'aks-lab-private-worker': {'uks-hub-aks-lab-worker-rg'},
        'aks-lab-network': {f'uks-{environment}-aks-lab-netw-rg-01', f'uks-{environment}-aks-lab-vnet-rg-01'},
        CONNECTIONS: {f'uks-{environment}-aks-lab-delivery-rg'},
        IDENTITIES: {f'uks-{environment}-aks-lab-delivery-rg'},
    }
    return own[component]


def permitted_group_grant(resource, instance, attrs, component, environment):
    slot = str(instance.get('index_key', '')).removeprefix(PROTECTED_ADMIN_GROUP + '/')
    return (component == 'aks-lab-aks' and environment == 'pprd' and not resource.get('module')
            and resource.get('name') == 'native_admin_cluster_user'
            and instance.get('index_key') == PROTECTED_ADMIN_GROUP + '/' + slot and slot in ('aks01', 'aks02')
            and attrs.get('scope', '').lower() == f'/subscriptions/{SUBSCRIPTION}/resourcegroups/uks-pprd-akslab-aks-rg/providers/microsoft.containerservice/managedclusters/uks-pprd-akslab-{slot}'
            and attrs.get('role_definition_name') in (None, 'Azure Kubernetes Service Cluster User Role')
            and attrs.get('role_definition_id', '').lower().endswith('/4abbcc35-e782-43d8-92c5-2d3f1bd2253f')
            and attrs.get('principal_type') == 'Group')


def validate_state(state, component, environment):
    expected_backend(component, environment)
    require(state.get('version') == 4 and isinstance(state.get('serial'), int) and bool(state.get('lineage')), 'Existing state lineage/serial required')
    managed = [resource for resource in state.get('resources', []) if resource.get('mode') == 'managed']
    for resource in managed:
        kind = resource.get('type', '')
        require(not kind.startswith('azuread_') and kind not in ('azurerm_resource_provider_registration', 'azurerm_subscription') and 'quota' not in kind.lower(), 'Shared directory objects, provider registration, subscription and quota are excluded')
        for instance in resource.get('instances', []):
            attrs = instance.get('attributes', {})
            if kind == 'azurerm_role_assignment':
                require(str(attrs.get('principal_id', '')).lower() != PROTECTED_ADMIN_GROUP or permitted_group_grant(resource, instance, attrs, component, environment), 'Shared admin grant is not one of the two exact lab-owned Cluster User assignments')
            resource_id = attrs.get('id', '')
            if isinstance(resource_id, str) and resource_id.lower().startswith('/subscriptions/'):
                require(resource_id.split('/')[2].lower() == SUBSCRIPTION, 'State resource belongs to another subscription')
            if kind.startswith('azurerm_'):
                scope = attrs.get('scope') if kind in ('azurerm_role_assignment', 'azurerm_role_definition') else resource_id
                require(isinstance(scope, str) and scope.lower().startswith('/subscriptions/' + SUBSCRIPTION + '/'), 'Azure state object has no approved subscription scope')
                match = re.search(r'/resourcegroups/([^/|]+)', scope.lower())
                require(match is not None, 'Subscription-wide objects/grants are outside component scope')
                allowed = resource_groups(component, environment)
                if kind == 'azurerm_role_assignment':
                    if component == 'aks-lab-aks':
                        allowed |= {'uks-pprd-aks-lab-vnet-rg-01', 'uks-hub-aks-lab-vnet-rg-01', 'uks-hub-aks-lab-netw-rg-01', 'uks-pprd-aks-lab-vault-rg'}
                    elif component == 'aks-lab-gateway':
                        allowed |= {'uks-pprd-aks-lab-vault-rg'}
                    elif component in (IDENTITIES, 'aks-lab-private-worker'):
                        allowed |= {f'uks-{env}-aks-lab-{suffix}' for env in ('hub', 'pprd', 'prd') for suffix in ('netw-rg-01', 'vnet-rg-01', 'tfstate-rsg')}
                        if component == IDENTITIES:
                            allowed |= {'uks-hub-aks-lab-worker-rg', 'uks-pprd-akslab-aks-rg', 'uks-pprd-aks-lab-vault-rg', 'uks-pprd-aks-lab-appgateway-rg'}
                if kind == 'azurerm_role_definition':
                    require(component == IDENTITIES and environment == 'hub' and resource.get('name') == 'state_endpoint_approver' and attrs.get('name') == 'uks-hub-aks-lab-state-endpoint-approver', 'Unrecognized custom role definition')
                    allowed = {f'uks-{env}-aks-lab-tfstate-rsg' for env in ('hub', 'pprd', 'prd')}
                if component == 'aks-lab-network' and kind in ('azurerm_private_dns_zone_virtual_network_link', 'azurerm_virtual_network_peering'):
                    allowed |= {'uks-hub-aks-lab-vnet-rg-01'}
                require(match[1] in allowed, 'State resource/group is outside this component boundary')
                if component == 'aks-lab-routes':
                    require(kind in ('azurerm_route_table', 'azurerm_route', 'azurerm_subnet_route_table_association'), 'Route state must not own its shared network resource group')
                if component == 'aks-lab-firewall':
                    require(kind in ('azurerm_firewall', 'azurerm_firewall_policy', 'azurerm_firewall_policy_rule_collection_group', 'azurerm_public_ip', 'azurerm_monitor_diagnostic_setting'), 'Firewall state must not own its shared network resource group')
            if resource.get('type', '').startswith('azuredevops_'):
                require(attrs.get('project_id') == PROJECT, 'State service connection belongs to another project')
    return {'lineage': state['lineage'], 'serial': state['serial'], 'managed_instances': sum(len(r.get('instances', [])) for r in managed)}


def validate_plan(plan, component, environment):
    validate_variables({name: entry['value'] for name, entry in plan.get('variables', {}).items()}, component, environment)
    deletes = []
    for change in plan.get('resource_changes', []):
        actions = change['change']['actions']
        require(actions in (['delete'], ['no-op'], ['read']), 'Destroy plan contains an unexpected create/update/replace action')
        if actions == ['delete']:
            deletes.append(change['address'])
    require(plan.get('errored') is not True, 'Terraform marked plan errored')
    return deletes


def plan_one(binding, output, expected_hash, operation="destroy"):
    require(operation in ("destroy", "detach-peerings") and (operation == "destroy" or binding["component"] == "aks-lab-network"), "Unsupported removal operation")
    require(re.fullmatch(r'[0-9a-f]{64}', expected_hash or '') is not None and binding['source_sha256'] == expected_hash, 'Review inventory and pass its exact --expected-source-sha256')
    private_path(PROFILE, directory=True)
    if binding['component'] == CONNECTIONS:
        private_path(PAT_FILE)
    create_output(output)
    work = output / 'source'
    work.mkdir(mode=0o700)
    source = BASE / binding['component']
    for name, expected in binding['files'].items():
        data = regular(source / name)
        require(digest(data) == expected, 'Source changed during snapshot; obtain a fresh inventory')
        destination = work / name
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private(destination, data)
    require(inventory(binding['component'], binding['environment']) == binding, 'Source changed during snapshot')
    write_private(output / 'inventory.json', json.dumps(binding, indent=2) + '\n')
    env = child_environment(output)
    info = json.loads(run(['az', 'account', 'show', '--subscription', SUBSCRIPTION, '--output', 'json'], work, env, 'Operator account check'))
    require(info.get('id') == SUBSCRIPTION and info.get('tenantId') == TENANT and info.get('user', {}).get('type') == 'user' and info.get('state') == 'Enabled', 'Isolated profile must be the intended active user account')
    version = json.loads(run([str(TERRAFORM), 'version', '-json'], work, env, 'Terraform version check'))
    require(version['terraform_version'] == '1.16.3', 'Use reviewed Terraform 1.16.3')
    backend = binding['backend']
    blob = ['az', 'storage', 'blob', 'exists', '--account-name', backend['storage_account_name'], '--container-name', backend['container_name'], '--name', backend['key'], '--auth-mode', 'login', '--subscription', SUBSCRIPTION, '--output', 'json']
    require(json.loads(run(blob, work, env, 'Existing state check')).get('exists') is True, 'State blob does not exist; refusing to initialize an empty replacement')
    metadata = blob_metadata(backend, work, env, output / 'blob-before.json')
    require(metadata.get('properties', {}).get('lease', {}).get('status') == 'unlocked', 'State already has a lease; inspect protected metadata and stop competing work; no unlock is attempted')
    backend_config = dict(backend, use_cli=True, use_oidc=False, use_msi=False)
    backend_file = output / 'backend.hcl'
    write_private(backend_file, ''.join(f'{key} = {json.dumps(value)}\n' for key, value in backend_config.items()))
    run([str(TERRAFORM), 'init', '-input=false', '-lockfile=readonly', '-no-color', '-backend-config=' + str(backend_file)], work, env, 'Isolated backend initialization')
    cache = json.loads(regular(Path(env['TF_DATA_DIR']) / 'terraform.tfstate'))
    validate_backend_cache(cache, backend)
    require(run([str(TERRAFORM), 'workspace', 'show'], work, env, 'Workspace check').decode().strip() == 'default', 'Only default workspace is supported')
    before = run([str(TERRAFORM), 'state', 'pull'], work, env, 'State snapshot')
    before_info = validate_state(json.loads(before), binding['component'], binding['environment'])
    write_private(output / 'state-before.tfstate', before)
    require(before_info['managed_instances'] > 0, 'No managed instances remain; snapshot saved, no destroy plan is necessary')
    if binding['component'] == CONNECTIONS:
        token = regular(PAT_FILE).decode().strip()
        require(token and not re.search(r'\s', token), 'Bootstrap PAT file is empty or malformed')
        env['AZDO_PERSONAL_ACCESS_TOKEN'] = token
        env['AZDO_ORG_SERVICE_URL'] = ORGANIZATION
    saved_plan = output / 'destroy.tfplan'
    command = [str(TERRAFORM), 'plan', *(['-destroy'] if operation == 'destroy' else []), '-refresh=true', '-input=false', '-lock=true', '-lock-timeout=60s', '-detailed-exitcode', '-no-color', '-out=' + str(saved_plan)]
    command += ['-var-file=' + str(work / name) for name in binding['var_files']]
    if binding["component"] == "aks-lab-network":
        # Disable cross-state data reads during removal, including later destroys.
        command.append("-var=enable_peerings=false")
    try:
        run(command, work, env, 'Destroy planning', allowed=(0, 2))
    except (ValueError, OSError):
        preserve_failed_plan(backend, work, env, output, binding['component'], binding['environment'])
        raise
    saved_plan.chmod(0o600)
    rendered = run([str(TERRAFORM), 'show', '-json', str(saved_plan)], work, env, 'Saved-plan inspection')
    plan = json.loads(rendered)
    deletes = validate_plan(plan, binding['component'], binding['environment'])
    if operation == "detach-peerings":
        require(all(change["type"] == "azurerm_virtual_network_peering"
                    for change in plan.get("resource_changes", [])
                    if change["change"]["actions"] == ["delete"]), "Peering plan would delete other resources")
    text = run([str(TERRAFORM), 'show', '-no-color', str(saved_plan)], work, env, 'Saved-plan review text')
    if binding['component'] == CONNECTIONS:
        token_bytes = env['AZDO_PERSONAL_ACCESS_TOKEN'].encode()
        require(token_bytes not in rendered and token_bytes not in text, 'Unexpected credential in plan rendering; keep run private and investigate')
        env.pop('AZDO_PERSONAL_ACCESS_TOKEN')
    write_private(output / 'destroy-plan.json', rendered)
    write_private(output / 'destroy-plan.txt', text)
    after = run([str(TERRAFORM), 'state', 'pull'], work, env, 'Post-plan state snapshot')
    after_info = validate_state(json.loads(after), binding['component'], binding['environment'])
    write_private(output / 'state-after.tfstate', after)
    metadata_after = blob_metadata(backend, work, env, output / 'blob-after.json')
    require(metadata_after.get('properties', {}).get('lease', {}).get('status') == 'unlocked', 'State remains leased after planning; saved plan is not qualified and no unlock is attempted')
    require(after_info == before_info and comparable_state(json.loads(after)) == comparable_state(json.loads(before)), 'State changed during planning; do not use this saved plan')
    require(inventory(binding['component'], binding['environment']) == binding, 'Original source changed during planning; review again before any separate apply')
    receipt = {'operation': operation, 'component': binding['component'], 'environment': binding['environment'], 'source_sha256': binding['source_sha256'], 'backend': backend, 'terraform_version': version['terraform_version'], 'state': before_info, 'plan_sha256': digest(regular(saved_plan)), 'state_before_sha256': digest(before), 'state_after_sha256': digest(after), 'delete_addresses': deletes, 'resource_apply_performed': False, 'state_migration_performed': False, 'status': 'destroy-plan-ready-for-independent-review'}
    write_private(output / 'receipt.json', json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'component': binding['component'], 'environment': binding['environment'], 'delete_count': len(deletes), 'private_output': str(output), 'apply_performed': False}))


def configure(path):
    global BASE, PRIVATE, PROFILE, PAT_FILE, TERRAFORM, SUBSCRIPTION, TENANT
    global PROJECT, PROTECTED_ADMIN_GROUP, ORGANIZATION, STORAGE_PREFIX
    private_path(path)
    config = json.loads(regular(path))
    expected = {"schema_version", "workspace", "private_evidence_root", "azure_config_dir",
                "bootstrap_pat_file", "terraform_binary", "subscription_id", "tenant_id",
                "azure_devops_project_id", "azure_devops_organization_url",
                "protected_admin_group_id", "storage_prefix"}
    require(set(config) == expected and config["schema_version"] == 1, "Unexpected teardown configuration schema")
    for field in ("subscription_id", "tenant_id", "azure_devops_project_id", "protected_admin_group_id"):
        require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", config[field]) is not None, "Expected explicit lowercase UUID: " + field)
    require(re.fullmatch(r"https://dev\.azure\.com/[A-Za-z0-9-]+/", config["azure_devops_organization_url"]) is not None, "Expected an explicit Azure DevOps organization URL")
    require(re.fullmatch(r"[a-z0-9]{3,8}", config["storage_prefix"]) is not None, "Storage prefix must be 3-8 lowercase letters/digits")
    for field in ("workspace", "private_evidence_root", "azure_config_dir", "bootstrap_pat_file", "terraform_binary"):
        path_value = Path(config[field])
        require(path_value.is_absolute() and not path_value.is_symlink(), "Expected explicit non-symlink absolute path: " + field)
    BASE = Path(config["workspace"])
    PRIVATE = Path(config["private_evidence_root"])
    PROFILE = Path(config["azure_config_dir"])
    PAT_FILE = Path(config["bootstrap_pat_file"])
    TERRAFORM = Path(config["terraform_binary"])
    SUBSCRIPTION = config["subscription_id"]
    TENANT = config["tenant_id"]
    PROJECT = config["azure_devops_project_id"]
    PROTECTED_ADMIN_GROUP = config["protected_admin_group_id"]
    ORGANIZATION = config["azure_devops_organization_url"]
    STORAGE_PREFIX = config["storage_prefix"]
    private_path(BASE, directory=True)
    private_path(PRIVATE, directory=True)
    require(not PRIVATE.resolve().is_relative_to(BASE.resolve()), "Recovery evidence must be outside the consumer workspace")
    return digest(regular(path))


def apply_one(binding, output, expected_plan):
    require(output.resolve().is_relative_to(PRIVATE.resolve()), "Plan directory escapes private evidence root")
    private_path(output, directory=True)
    receipt = json.loads(regular(output / "receipt.json"))
    saved = output / "destroy.tfplan"
    require(re.fullmatch(r"[0-9a-f]{64}", expected_plan or "") is not None
            and digest(regular(saved)) == expected_plan == receipt["plan_sha256"], "Reviewed saved-plan SHA256 does not match")
    require(receipt["status"] == "destroy-plan-ready-for-independent-review"
            and receipt["source_sha256"] == binding["source_sha256"]
            and receipt["backend"] == binding["backend"], "Plan source/backend differs from current inventory")
    require(not (output / "apply-result.json").exists(), "This plan already has an apply result; re-plan before another attempt")
    work = output / "source"
    for name, expected in binding["files"].items():
        require(digest(regular(work / name)) == expected, "Saved source changed: " + name)
    env = child_environment(output)
    validate_backend_cache(json.loads(regular(Path(env["TF_DATA_DIR"]) / "terraform.tfstate")), binding["backend"])
    info = json.loads(run(["az", "account", "show", "--subscription", SUBSCRIPTION, "--output", "json"], work, env, "Operator account check"))
    require(info.get("id") == SUBSCRIPTION and info.get("tenantId") == TENANT
            and info.get("user", {}).get("type") == "user", "Wrong cleanup operator account")
    current = run([str(TERRAFORM), "state", "pull"], work, env, "Pre-apply state snapshot")
    validate_state(json.loads(current), binding["component"], binding["environment"])
    require(comparable_state(json.loads(current)) == comparable_state(json.loads(regular(output / "state-after.tfstate"))), "State changed since reviewed plan; re-plan")
    plan = json.loads(run([str(TERRAFORM), "show", "-json", str(saved)], work, env, "Recheck saved plan"))
    require(validate_plan(plan, binding["component"], binding["environment"]) == receipt["delete_addresses"], "Saved delete set changed")
    if binding["component"] == CONNECTIONS:
        private_path(PAT_FILE)
        env["AZDO_PERSONAL_ACCESS_TOKEN"] = regular(PAT_FILE).decode().strip()
        env["AZDO_ORG_SERVICE_URL"] = ORGANIZATION
    with open(output / "apply.log", "xb", opener=lambda name, flags: os.open(name, flags, 0o600)) as log:
        result = subprocess.run([str(TERRAFORM), "apply", "-input=false", "-lock=true",
                                 "-lock-timeout=60s", "-no-color", str(saved)],
                                cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
    status = {"component": binding["component"], "environment": binding["environment"],
              "plan_sha256": expected_plan, "returncode": result.returncode, "status": "failed"}
    if result.returncode == 0:
        after = run([str(TERRAFORM), "state", "pull"], work, env, "Final state snapshot")
        write_private(output / "state-final.tfstate", after)
        remaining = validate_state(json.loads(after), binding["component"], binding["environment"])
        status["remaining_managed_instances"] = remaining["managed_instances"]
        if receipt.get("operation", "destroy") == "detach-peerings":
            resources = json.loads(after).get("resources", [])
            peers = [r for r in resources if r.get("mode") == "managed"
                     and r.get("type") == "azurerm_virtual_network_peering" and r.get("instances")]
            before_count = receipt["state"]["managed_instances"]
            if not peers and remaining["managed_instances"] == before_count - len(receipt["delete_addresses"]):
                status["status"] = "peerings-detached"
        elif remaining["managed_instances"] == 0:
            status["status"] = "removed"
    write_private(output / "apply-result.json", json.dumps(status, indent=2) + "\n")
    require(status["status"] in ("removed", "peerings-detached"), "Removal did not complete; inspect private apply.log and current state before re-planning")
    print(json.dumps(status))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Mode-0600 private configuration; never commit real values")
    parser.add_argument("--component", required=True, choices=sorted(TARGETS))
    parser.add_argument("--environment", required=True, choices=["hub", "pprd", "prd"])
    parser.add_argument("--mode", choices=["inventory", "plan", "detach-plan", "apply"], default="inventory")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--output", type=Path, help="Exclusive private plan directory (existing only for apply)")
    args = parser.parse_args(argv)
    os.umask(0o077)
    configure(args.config)
    binding = inventory(args.component, args.environment)
    if args.mode == "inventory":
        require(args.output is None and args.expected_source_sha256 is None and args.expected_plan_sha256 is None, "Inventory has no apply/plan arguments")
        print(json.dumps(dict(binding, cloud_access_performed=False, resource_apply_performed=False), indent=2))
    elif args.mode in ("plan", "detach-plan"):
        require(args.output is not None and args.expected_plan_sha256 is None, "Plan requires a new output directory")
        plan_one(binding, args.output, args.expected_source_sha256, "detach-peerings" if args.mode == "detach-plan" else "destroy")
    else:
        require(args.output is not None and args.expected_source_sha256 is None, "Apply requires its reviewed plan directory/hash")
        apply_one(binding, args.output, args.expected_plan_sha256)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print("Teardown stopped: " + str(exc), file=sys.stderr)
        sys.exit(1)
