# GNU General Public License v3.0+
# (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from unittest.mock import patch

from ansible_collections.cisco.nxos.plugins.modules import nxos_interfaces
from ansible_collections.cisco.nxos.tests.unit.modules.utils import set_module_args

from .nxos_module import TestNxosModule


class TestNxosInterfacesDefaults(TestNxosModule):
    module = nxos_interfaces

    def setUp(self):
        super(TestNxosInterfacesDefaults, self).setUp()
        connection_patch = patch(
            "ansible_collections.ansible.netcommon.plugins.module_utils.network.common.rm_base."
            "resource_module_base.get_resource_connection",
        )
        self.connection = connection_patch.start().return_value
        self.addCleanup(connection_patch.stop)
        facts_connection_patch = patch(
            "ansible_collections.ansible.netcommon.plugins.module_utils.network.common.facts."
            "facts.get_resource_connection",
            return_value=self.connection,
        )
        facts_connection_patch.start()
        self.addCleanup(facts_connection_patch.stop)
        defaults_patch = patch(
            "ansible_collections.cisco.nxos.plugins.module_utils.network.nxos.config.interfaces."
            "interfaces.Interfaces.get_interface_defaults",
            return_value={"default_mode": "layer3", "L2_enabled": True},
        )
        defaults_patch.start()
        self.addCleanup(defaults_patch.stop)
        self.running = "interface Ethernet1/1\n"
        self.running_all = "interface Ethernet1/1\n  shutdown\n"
        self.connection.get.side_effect = self.get_config

    def get_config(self, command):
        if command == "show running-config | section ^interface":
            return self.running
        if command == "show running-config all | section ^interface":
            return self.running_all
        self.fail("Unexpected command: {0}".format(command))

    def test_implicit_shutdown_is_idempotent(self):
        for state in ("merged", "replaced", "overridden"):
            for check_mode in (False, True):
                with self.subTest(state=state, check_mode=check_mode):
                    set_module_args(
                        dict(
                            config=[dict(name="Ethernet1/1", enabled=False)],
                            state=state,
                            _ansible_check_mode=check_mode,
                        ),
                    )
                    result = self.execute_module(changed=False)
                    self.assertEqual(result["commands"], [])
                    self.assertFalse(result["before"][0]["enabled"])

    def test_implicit_shutdown_can_be_enabled(self):
        set_module_args(dict(config=[dict(name="Ethernet1/1", enabled=True)], state="merged"))
        self.execute_module(
            changed=True,
            commands=["interface Ethernet1/1", "no shutdown"],
            sort=False,
        )

    def test_device_reported_admin_defaults_for_interface_types(self):
        # The device, not a platform-name heuristic, supplies the effective state.
        for name in (
            "Ethernet1/1",
            "Ethernet1/1.100",
            "Vlan100",
            "loopback0",
            "port-channel10",
            "port-channel10.100",
            "mgmt0",
            "nve1",
        ):
            for enabled in (False, True):
                for state in ("merged", "replaced", "overridden"):
                    with self.subTest(name=name, enabled=enabled, state=state):
                        self.running = "interface {0}\n".format(name)
                        self.running_all = self.running + (
                            "  no shutdown\n" if enabled else "  shutdown\n"
                        )
                        set_module_args(
                            dict(config=[dict(name=name, enabled=enabled)], state=state),
                        )
                        self.execute_module(changed=False)

    def test_implicit_no_shutdown_can_be_disabled(self):
        self.running_all = "interface Ethernet1/1\n  no shutdown\n"
        set_module_args(dict(config=[dict(name="Ethernet1/1", enabled=False)], state="merged"))
        self.execute_module(
            changed=True,
            commands=["interface Ethernet1/1", "shutdown"],
            sort=False,
        )

    def test_l2_shutdown_defaults(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.running = "interface Ethernet1/1\n  switchport\n"
                self.running_all = self.running + ("  no shutdown\n" if enabled else "  shutdown\n")
                set_module_args(
                    dict(config=[dict(name="Ethernet1/1", mode="layer2", enabled=enabled)]),
                )
                self.execute_module(changed=False)

    def test_explicit_shutdown_states_do_not_need_defaults(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.running = "interface Ethernet1/1\n" + (
                    "  no shutdown\n" if enabled else "  shutdown\n"
                )
                self.connection.get.reset_mock()
                set_module_args(dict(config=[dict(name="Ethernet1/1", enabled=enabled)]))
                self.execute_module(changed=False)
                self.connection.get.assert_called_once_with(
                    "show running-config | section ^interface",
                )

    def test_gathered_only_adds_missing_enabled_not_other_defaults(self):
        self.running = "interface Ethernet1/1\ninterface Ethernet1/2\n  no shutdown\n"
        self.running_all = (
            "interface Ethernet1/1\n  shutdown\n  mtu 1500\n  speed 1000\n  no switchport\n"
            "interface Ethernet1/2\n  shutdown\n"
            "interface Ethernet1/3\n  shutdown\n"
        )
        set_module_args(dict(state="gathered"))
        result = self.execute_module(changed=False)
        self.assertEqual(
            result["gathered"],
            [dict(name="Ethernet1/1", enabled=False), dict(name="Ethernet1/2", enabled=True)],
        )

    def test_missing_state_in_all_output_is_not_guessed(self):
        self.running_all = "interface Ethernet1/1\n"
        set_module_args(dict(config=[dict(name="Ethernet1/1", enabled=False)]))
        self.execute_module(changed=True, commands=["interface Ethernet1/1", "shutdown"])

    def test_new_interface_still_gets_explicit_admin_state(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.running = "interface Ethernet1/1\n  shutdown\n"
                set_module_args(dict(config=[dict(name="loopback100", enabled=enabled)]))
                self.execute_module(
                    changed=True,
                    commands=["interface loopback100", "no shutdown" if enabled else "shutdown"],
                    sort=False,
                )

    def test_mode_change_reapplies_enabled_after_mode(self):
        for mode, before_mode, mode_command in (
            ("layer2", "  no switchport\n", "switchport"),
            ("layer3", "  switchport\n", "no switchport"),
        ):
            for enabled in (False, True):
                with self.subTest(mode=mode, enabled=enabled):
                    self.running = "interface Ethernet1/1\n" + before_mode
                    self.running_all = self.running + (
                        "  no shutdown\n" if enabled else "  shutdown\n"
                    )
                    set_module_args(
                        dict(config=[dict(name="Ethernet1/1", mode=mode, enabled=enabled)]),
                    )
                    self.execute_module(
                        changed=True,
                        commands=[
                            "interface Ethernet1/1",
                            mode_command,
                            "no shutdown" if enabled else "shutdown",
                        ],
                        sort=False,
                    )

    def test_overridden_omitted_disabled_interface_is_idempotent(self):
        self.running = "interface Ethernet1/1\ninterface Ethernet1/2\n"
        self.running_all = "interface Ethernet1/1\n  shutdown\ninterface Ethernet1/2\n  shutdown\n"
        set_module_args(dict(config=[dict(name="Ethernet1/1", enabled=False)], state="overridden"))
        self.execute_module(changed=False)

    def test_overridden_omitted_enabled_interface_is_shutdown(self):
        self.running = "interface Ethernet1/1\ninterface Ethernet1/2\n"
        self.running_all = (
            "interface Ethernet1/1\n  shutdown\ninterface Ethernet1/2\n  no shutdown\n"
        )
        set_module_args(dict(config=[dict(name="Ethernet1/1", enabled=False)], state="overridden"))
        self.execute_module(
            changed=True,
            commands=["interface Ethernet1/2", "shutdown"],
            sort=False,
        )

    def test_second_run_after_disabling_is_idempotent(self):
        self.running = "interface Ethernet1/1\n  no shutdown\n"
        set_module_args(dict(config=[dict(name="Ethernet1/1", enabled=False)], state="merged"))
        self.execute_module(changed=True, commands=["interface Ethernet1/1", "shutdown"])
        # NX-OS hides shutdown again after it returns to the implicit default.
        self.running = "interface Ethernet1/1\n"
        self.running_all = "interface Ethernet1/1\n  shutdown\n"
        set_module_args(dict(config=[dict(name="Ethernet1/1", enabled=False)], state="merged"))
        self.execute_module(changed=False)

    def test_unmanaged_enabled_does_not_generate_commands(self):
        for state in ("merged", "replaced", "overridden"):
            with self.subTest(state=state):
                set_module_args(dict(config=[dict(name="Ethernet1/1")], state=state))
                self.execute_module(changed=False)

    def test_config_after_change_keeps_only_admin_defaults(self):
        self.connection.get.side_effect = [
            "interface Ethernet1/1\n  no shutdown\n",
            "interface Ethernet1/1\n",
            "interface Ethernet1/1\n  shutdown\n  mtu 1500\n",
        ]
        set_module_args(dict(config=[dict(name="Ethernet1/1", enabled=False)], state="merged"))
        result = self.execute_module(changed=True)
        self.assertEqual(result["before"], [dict(name="Ethernet1/1", enabled=True)])
        self.assertEqual(result["after"], [dict(name="Ethernet1/1", enabled=False)])

    def test_parsed_does_not_query_device_or_invent_defaults(self):
        set_module_args(dict(running_config=self.running, state="parsed"))
        result = self.execute_module(changed=False)
        self.assertEqual(result["parsed"], [dict(name="Ethernet1/1")])
        self.connection.get.assert_not_called()

    def test_rendered_does_not_query_device(self):
        set_module_args(dict(config=[dict(name="Ethernet1/1", enabled=False)], state="rendered"))
        result = self.execute_module(changed=False)
        self.assertEqual(result["rendered"], ["interface Ethernet1/1", "shutdown"])
        self.connection.get.assert_not_called()
