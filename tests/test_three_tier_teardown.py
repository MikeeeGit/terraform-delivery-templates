"""Offline guards only: no Azure or Terraform process is invoked."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import importlib.util
_spec = importlib.util.spec_from_file_location("three_tier_teardown", Path(__file__).resolve().parents[1] / "scripts/azure/three_tier_teardown.py")
helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helper)


def fixture(base, component='aks-lab-firewall', environment='hub'):
    root = base / component
    root.mkdir(parents=True)
    for path, contents in {
        'backend.tf': 'terraform { backend "azurerm" {} }\n',
        'providers.tf': 'provider "azurerm" { resource_provider_registrations = "none" }\n',
        '.terraform.lock.hcl': '# fixture lock\n',
        'config/global.tfvars': f'tenant_id = "{helper.TENANT}"\n',
        f'config/uks/{environment}/{environment}.tfvars': f'environment = "{environment}"\n',
    }.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    config = {'tenant_id': helper.TENANT, 'prefix': helper.STORAGE_PREFIX, 'regions': ['uks'], 'secondary_region': 'uks', 'subscriptions': {'hub': helper.SUBSCRIPTION, 'pprd': helper.SUBSCRIPTION, 'prd': helper.SUBSCRIPTION}, 'environments': {environment: {'subscription_alias': environment, 'backend_environment': environment}}, 'backend': {'subscription_alias': 'hub', 'resource_group': '{secondary_region}-{backend_environment}-aks-lab-tfstate-rsg', 'storage_account': '{secondary_region}{backend_environment}{prefix}tfstatesa', 'container': '{secondary_region}-{backend_environment}-azdo-tfstate', 'key': '{repository}-{environment}-{region}.tfstate'}}
    (root / 'delivery.azure.json').write_text(json.dumps(config))
    return root


class GuardTests(unittest.TestCase):
    def test_check_order_is_semantic_but_resource_and_serial_changes_are_not(self):
        state = {"lineage": "same", "serial": 7, "resources": [{"value": "original"}],
                 "check_results": [{"config_addr": "resource.example", "status": "pass",
                                    "objects": [{"object_addr": "b", "status": "pass"},
                                                {"object_addr": "a", "status": "pass"}]}]}
        reordered = json.loads(json.dumps(state))
        reordered["check_results"][0]["objects"].reverse()
        self.assertEqual(helper.comparable_state(state), helper.comparable_state(reordered))
        for field, value in (("serial", 8), ("lineage", "different"),
                             ("resources", [{"value": "changed"}])):
            changed = dict(reordered, **{field: value})
            self.assertNotEqual(helper.comparable_state(state), helper.comparable_state(changed))
        reordered["check_results"][0]["objects"][0]["status"] = "fail"
        self.assertNotEqual(helper.comparable_state(state), helper.comparable_state(reordered))

    def test_fixed_whitelist_and_bootstrap_excluded(self):
        for component, environments in helper.TARGETS.items():
            for environment in environments:
                result = helper.expected_backend(component, environment)
                self.assertEqual(result['key'], f'{component}-{environment}-uks.tfstate')
                self.assertEqual(result['subscription_id'], helper.SUBSCRIPTION)
        for component, environment in [('bootstrap-state', 'hub'), ('../aks-lab-aks', 'pprd'), ('aks-lab-aks', 'prd'), ('aks-lab-routes', 'pprd')]:
            with self.assertRaises(ValueError):
                helper.expected_backend(component, environment)

    def test_inventory_is_offline_and_preserves_ignored_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = fixture(base)
            (root / 'generated_override.tf').write_text('# reviewed generated provider\n')
            with patch.object(helper.subprocess, 'run', side_effect=AssertionError('No subprocess for inventory')):
                first = helper.inventory('aks-lab-firewall', 'hub', base)
            self.assertIn('generated_override.tf', first['files'])
            (root / 'generated_override.tf').write_text('# changed\n')
            second = helper.inventory('aks-lab-firewall', 'hub', base)
            self.assertNotEqual(first['source_sha256'], second['source_sha256'])

    def test_wrong_backend_rejected_before_any_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = fixture(base)
            path = root / 'delivery.azure.json'; config = json.loads(path.read_text())
            config['backend']['key'] = 'another-root.tfstate'; path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'backend'):
                helper.inventory('aks-lab-firewall', 'hub', base)

    def test_wrong_input_environment_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = fixture(base)
            (root / 'config/uks/hub/hub.tfvars').write_text('environment = "pprd"\n')
            with self.assertRaisesRegex(ValueError, 'environment mismatch'):
                helper.inventory('aks-lab-firewall', 'hub', base)

    def test_symlink_and_external_execution_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = fixture(base)
            (root / 'generated.tf').write_text('data "external" "unsafe" {}\n')
            with self.assertRaisesRegex(ValueError, 'external execution'):
                helper.inventory('aks-lab-firewall', 'hub', base)
            (root / 'generated.tf').unlink()
            (root / 'generated.tf').symlink_to(root / 'providers.tf')
            with self.assertRaisesRegex(ValueError, 'non-symlink'):
                helper.inventory('aks-lab-firewall', 'hub', base)

    def test_inherited_credentials_and_cli_overrides_removed(self):
        original = {'PATH': '/bin', 'HOME': '/home/test', 'ARM_CLIENT_SECRET': 'secret', 'ARM_USE_OIDC': 'true', 'AZURE_CONFIG_DIR': '/wrong', 'AZDO_PERSONAL_ACCESS_TOKEN': 'secret', 'AZURE_DEVOPS_EXT_PAT': 'secret', 'TF_CLI_ARGS_plan': '-target=x', 'TF_VAR_environment': 'prd', 'TF_LOG': 'TRACE', 'TF_WORKSPACE': 'wrong', 'SYSTEM_ACCESSTOKEN': 'secret'}
        env = helper.child_environment(Path('/private/run'), original)
        self.assertNotIn('secret', env.values())
        self.assertNotIn('TF_CLI_ARGS_plan', env)
        self.assertNotIn('TF_VAR_environment', env)
        self.assertNotIn('TF_LOG', env)
        self.assertEqual(env['ARM_USE_OIDC'], 'false')
        self.assertEqual(env['AZURE_CONFIG_DIR'], str(helper.PROFILE))
        self.assertEqual(env['TF_WORKSPACE'], 'default')

    def test_backend_cache_must_match_exact_key_and_cli(self):
        expected = helper.expected_backend('aks-lab-aks', 'pprd')
        cache = {'backend': {'type': 'azurerm', 'config': dict(expected, use_cli=True, use_oidc=False, use_msi=False)}}
        helper.validate_backend_cache(cache, expected)
        cache['backend']['config']['key'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'backend mismatch'):
            helper.validate_backend_cache(cache, expected)

    def test_state_rejects_other_subscription_and_shared_objects(self):
        def state(kind, attrs):
            return {'version': 4, 'serial': 1, 'lineage': 'fixture', 'resources': [{'mode': 'managed', 'type': kind, 'instances': [{'attributes': attrs}]}]}
        cases = [state('azurerm_resource_group', {'id': '/subscriptions/other/resourceGroups/test'}), state('azuread_group', {'id': helper.PROTECTED_ADMIN_GROUP}), state('azurerm_role_assignment', {'principal_id': helper.PROTECTED_ADMIN_GROUP}), state('azurerm_resource_provider_registration', {}), state('azurerm_quota', {})]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                helper.validate_state(value, 'aks-lab-aks', 'pprd')

    def test_exact_owned_admin_cluster_user_grants_allowed_only(self):
        for slot in ('aks01', 'aks02'):
            scope = f'/subscriptions/{helper.SUBSCRIPTION}/resourceGroups/uks-pprd-akslab-aks-rg/providers/Microsoft.ContainerService/managedClusters/uks-pprd-akslab-{slot}'
            attrs = {'id': scope + '/providers/Microsoft.Authorization/roleAssignments/fixture', 'scope': scope, 'principal_id': helper.PROTECTED_ADMIN_GROUP, 'principal_type': 'Group', 'role_definition_name': 'Azure Kubernetes Service Cluster User Role', 'role_definition_id': f'/subscriptions/{helper.SUBSCRIPTION}/providers/Microsoft.Authorization/roleDefinitions/4abbcc35-e782-43d8-92c5-2d3f1bd2253f'}
            resource = {'mode': 'managed', 'type': 'azurerm_role_assignment', 'name': 'native_admin_cluster_user', 'instances': [{'index_key': helper.PROTECTED_ADMIN_GROUP + '/' + slot, 'attributes': attrs}]}
            state = {'version': 4, 'serial': 1, 'lineage': 'fixture', 'resources': [resource]}
            helper.validate_state(state, 'aks-lab-aks', 'pprd')
            for key, value in [('scope', '/subscriptions/' + helper.SUBSCRIPTION), ('role_definition_name', 'Owner'), ('role_definition_id', '/other'), ('principal_type', 'ServicePrincipal')]:
                original = attrs[key]; attrs[key] = value
                with self.assertRaisesRegex(ValueError, 'two exact'):
                    helper.validate_state(state, 'aks-lab-aks', 'pprd')
                attrs[key] = original
            resource['name'] = 'inherited_existing_role'
            with self.assertRaisesRegex(ValueError, 'two exact'):
                helper.validate_state(state, 'aks-lab-aks', 'pprd')

    def test_same_subscription_unrelated_resource_group_rejected(self):
        state = {'version': 4, 'serial': 1, 'lineage': 'fixture', 'resources': [{'mode': 'managed', 'type': 'azurerm_firewall', 'instances': [{'attributes': {'id': f'/subscriptions/{helper.SUBSCRIPTION}/resourceGroups/existing-pprd-rg/providers/Microsoft.Network/azureFirewalls/existing'}}]}]}
        with self.assertRaisesRegex(ValueError, 'component boundary'):
            helper.validate_state(state, 'aks-lab-firewall', 'hub')

    def test_literal_runtime_file_dependencies_copied_and_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = fixture(base)
            (root / 'scripts').mkdir()
            (root / 'scripts/cloud-init.yaml').write_text('# nonsecret fixture\n')
            (root / 'assets.tf').write_text('locals { init = templatefile("${path.root}/scripts/cloud-init.yaml", {}) }\n')
            binding = helper.inventory('aks-lab-firewall', 'hub', base)
            self.assertIn('scripts/cloud-init.yaml', binding['files'])
            self.assertIn('scripts/cloud-init.yaml', binding['file_dependencies'])
            (root / 'assets.tf').write_text('locals { init = file("../other/secret") }\n')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                helper.inventory('aks-lab-firewall', 'hub', base)
            (root / 'assets.tf').write_text('locals { init = file(var.private_path) }\n')
            with self.assertRaisesRegex(ValueError, 'non-literal'):
                helper.inventory('aks-lab-firewall', 'hub', base)

    def test_plan_rejects_create_update_and_wrong_environment(self):
        values = {'tenant_id': helper.TENANT, 'environment': 'hub', 'subscription': 'hub', 'location_abbreviated': 'uks', 'subscription_id_map': {'hub': helper.SUBSCRIPTION}}
        plan = {'variables': {k: {'value': v} for k, v in values.items()}, 'resource_changes': [{'address': 'azurerm_firewall.test', 'change': {'actions': ['delete']}}]}
        self.assertEqual(helper.validate_plan(plan, 'aks-lab-firewall', 'hub'), ['azurerm_firewall.test'])
        for actions in [['create'], ['update'], ['delete', 'create']]:
            plan['resource_changes'][0]['change']['actions'] = actions
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                helper.validate_plan(plan, 'aks-lab-firewall', 'hub')
        plan['variables']['environment']['value'] = 'prd'
        with self.assertRaisesRegex(ValueError, 'input mismatch'):
            helper.validate_plan(plan, 'aks-lab-firewall', 'hub')

    def test_output_exclusive_private_and_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp); private.chmod(0o700)
            output = private / 'run'
            helper.create_output(output, private)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            helper.write_private(output / 'state', 'private data')
            self.assertEqual((output / 'state').stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError): helper.create_output(output, private)
            (private / '.git').mkdir()
            with self.assertRaisesRegex(ValueError, 'Git tree'): helper.create_output(private / 'other', private)

    def test_orchestration_only_snapshots_and_destroy_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'lab'; root = fixture(base)
            private = Path(tmp) / 'private'; private.mkdir(mode=0o700)
            profile = Path(tmp) / 'operator'; profile.mkdir(mode=0o700)
            output = private / 'run'
            values = {'tenant_id': helper.TENANT, 'environment': 'hub', 'subscription': 'hub', 'location_abbreviated': 'uks', 'subscription_id_map': {'hub': helper.SUBSCRIPTION}}
            state = {'version': 4, 'serial': 2, 'lineage': 'same-lineage', 'resources': [{'mode': 'managed', 'type': 'azurerm_firewall', 'instances': [{'attributes': {'id': '/subscriptions/' + helper.SUBSCRIPTION + '/resourceGroups/uks-hub-aks-lab-vnet-rg-01/providers/Microsoft.Network/azureFirewalls/test'}}]}]}
            calls = []
            def fake(command, cwd, env, stage, allowed=(0,)):
                calls.append(command)
                self.assertEqual(cwd, output / 'source')
                self.assertEqual(env['AZURE_CONFIG_DIR'], str(profile))
                if command[0] == 'az':
                    if command[1] == 'account': return json.dumps({'id': helper.SUBSCRIPTION, 'tenantId': helper.TENANT, 'user': {'type': 'user'}, 'state': 'Enabled'}).encode()
                    if command[3] == 'exists': return b'{"exists":true}'
                    return json.dumps({'name': helper.expected_backend('aks-lab-firewall', 'hub')['key'], 'properties': {'etag': 'fixture-etag', 'lease': {'status': 'unlocked'}}, 'metadata': {}}).encode()
                operation = command[1]
                if operation == 'version': return b'{"terraform_version":"1.16.3"}'
                if operation == 'init':
                    data = Path(env['TF_DATA_DIR']); data.mkdir(mode=0o700)
                    helper.write_private(data / 'terraform.tfstate', json.dumps({'backend': {'type': 'azurerm', 'config': dict(helper.expected_backend('aks-lab-firewall', 'hub'), use_cli=True, use_oidc=False, use_msi=False)}}))
                    return b''
                if operation == 'workspace': return b'default\n'
                if operation == 'state': return json.dumps(state).encode()
                if operation == 'plan':
                    helper.write_private(output / 'destroy.tfplan', b'fixture binary plan')
                    return b''
                if operation == 'show' and '-json' in command:
                    return json.dumps({'variables': {k: {'value': v} for k, v in values.items()}, 'resource_changes': [{'address': 'azurerm_firewall.test', 'change': {'actions': ['delete']}}]}).encode()
                if operation == 'show': return b'1 destroy, 0 create, 0 update'
                raise AssertionError(command)
            with patch.multiple(helper, BASE=base, PRIVATE=private, PROFILE=profile), patch.object(helper, 'run', side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
                binding = helper.inventory('aks-lab-firewall', 'hub')
                with self.assertRaisesRegex(ValueError, 'expected-source-sha256'):
                    helper.plan_one(binding, output, '0' * 64)
                self.assertFalse(output.exists())
                helper.plan_one(binding, output, binding['source_sha256'])
            self.assertFalse((root / '.terraform').exists())
            self.assertFalse(any(any(arg in ('apply', 'destroy', 'force-unlock', '-migrate-state', '-force-copy', '-lock=false', '-refresh=false') or arg.startswith('-target=') for arg in command) for command in calls))
            plan_command = next(command for command in calls if len(command) > 1 and command[1] == 'plan')
            self.assertIn('-destroy', plan_command)
            self.assertIn('-lock=true', plan_command)
            self.assertEqual((output / 'state-before.tfstate').read_bytes(), (output / 'state-after.tfstate').read_bytes())
            receipt = json.loads((output / 'receipt.json').read_text())
            self.assertFalse(receipt['resource_apply_performed'])
            self.assertFalse(receipt['state_migration_performed'])

    def test_failure_retains_lease_metadata_and_snapshot_without_unlock(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp); output.chmod(0o700)
            backend = helper.expected_backend('aks-lab-firewall', 'hub')
            state = {'version': 4, 'serial': 7, 'lineage': 'fixture', 'resources': []}
            metadata = {'name': backend['key'], 'properties': {'etag': 'exact-etag', 'lease': {'status': 'locked', 'state': 'leased'}}, 'metadata': {'terraformlockid': 'opaque-lock-metadata'}}
            commands = []
            def fake(command, *args, **kwargs):
                commands.append(command)
                return json.dumps(metadata if command[0] == 'az' else state).encode()
            with patch.object(helper, 'run', side_effect=fake):
                helper.preserve_failed_plan(backend, output, {}, output, 'aks-lab-firewall', 'hub')
            failure = json.loads((output / 'failure.json').read_text())
            self.assertTrue(failure['blob_metadata_saved'])
            self.assertTrue(failure['state_snapshot_saved'])
            self.assertFalse(failure['automatic_unlock_attempted'])
            self.assertEqual(json.loads((output / 'blob-after-failure.json').read_text()), metadata)
            self.assertEqual(commands[0][:4], ['az', 'storage', 'blob', 'show'])
            self.assertEqual(commands[1][1:], ['state', 'pull'])


if __name__ == '__main__':
    unittest.main()
