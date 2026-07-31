# -*- coding: utf-8 -*-
# Copyright 2025 Red Hat
# GNU General Public License v3.0+
# (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function


__metaclass__ = type

"""
The nxos l2_interfaces fact class
It is in this file the configuration is collected from the device
for a given resource, parsed, and the facts tree is populated
based on the configuration.
"""
import re

from ansible_collections.ansible.netcommon.plugins.module_utils.network.common import (
    utils,
)

from ansible_collections.cisco.nxos.plugins.module_utils.network.nxos.argspec.l2_interfaces.l2_interfaces import (
    L2_interfacesArgs,
)
from ansible_collections.cisco.nxos.plugins.module_utils.network.nxos.rm_templates.l2_interfaces import (
    L2_interfacesTemplate,
)
from ansible_collections.cisco.nxos.plugins.module_utils.network.nxos.utils.utils import (
    get_port_channel_members,
    normalize_interface,
)


class L2_interfacesFacts(object):
    """The nxos l2_interfaces facts class"""

    def __init__(self, module, subspec="config", options="options"):
        self._module = module
        self.argument_spec = L2_interfacesArgs.argument_spec

    def _get_interface_config(self, connection):
        # Use "all" so that default (hidden) lines such as
        # "switchport mode access" are rendered as well. Without it the
        # default switchport mode is invisible in the running-config, which
        # made the resource module believe the mode was unset and caused it
        # to re-issue "switchport mode access" on every run (non-idempotent).
        return connection.get("show running-config all | section ^interface")

    def _default_for_allowed_vlans(self, parsed_config):
        """Handle default for allowed vlans"""

        # Process allowed_vlans
        for interface in parsed_config:
            # if trunk and allowed vlan is empty then apply default
            # check if ...allowed vlan none command is not there
            # if vlan none command is there then don't apply default
            if interface.get("trunk"):
                if not interface.get("trunk", {}).get("allowed_vlans") and not interface.get(
                    "trunk",
                    {},
                ).get("allowed_vlans_none"):
                    interface["trunk"]["allowed_vlans"] = "1-4094"

    def _strip_default_values(self, parsed_config):
        """Remove default values that are only visible because the config is
        gathered with the ``all`` keyword.

        ``show running-config all`` renders otherwise-hidden defaults such as
        ``switchport access vlan 1`` and ``switchport trunk native vlan 1`` on
        every interface. These are not real configuration and must not be
        reported as facts, otherwise ``overridden``/``replaced`` would emit
        spurious negation commands (e.g. ``no switchport access vlan 1``).

        Note: gathering with ``all`` is required so that the (default) line
        ``switchport mode access`` is visible and the mode can be detected
        idempotently.
        """
        for interface in parsed_config:
            mode = interface.get("mode")

            # default access vlan 1 is invisible in a normal running-config
            access = interface.get("access")
            if access and str(access.get("vlan")) == "1":
                interface.pop("access", None)

            # default native vlan 1 is invisible in a normal running-config
            trunk = interface.get("trunk")
            if trunk and str(trunk.get("native_vlan")) == "1":
                trunk.pop("native_vlan", None)

            # Trunk parameters are inactive when ``show running-config all``
            # explicitly reports a non-trunk mode. If mode is absent, however,
            # the input may be a normal running-config or parsed input where
            # trunk attributes are explicit and must be preserved.
            if mode is not None and mode != "trunk" and interface.get("trunk"):
                interface.pop("trunk", None)

            # drop an emptied trunk dict
            if interface.get("trunk") == {}:
                interface.pop("trunk", None)

    def populate_facts(self, connection, ansible_facts, data=None):
        """Populate the facts for L2_interfaces network resource

        :param connection: the device connection
        :param ansible_facts: Facts dictionary
        :param data: previously collected conf

        :rtype: dictionary
        :returns: facts
        """
        facts = {}
        objs = []

        if not data:
            data = self._get_interface_config(connection)

        data = self._flatten_vlans(data)

        # parse native config using the L2_interfaces template
        l2_interfaces_parser = L2_interfacesTemplate(lines=data.splitlines(), module=self._module)
        objs = list(l2_interfaces_parser.parse().values())

        # process defaults for allowed vlan
        self._default_for_allowed_vlans(objs)

        # remove default values that are only present because of "all"
        self._strip_default_values(objs)

        pc_members = get_port_channel_members(data)
        self._module._l2_pc_members = pc_members
        objs = [obj for obj in objs if normalize_interface(obj.get("name", "")) not in pc_members]

        ansible_facts["ansible_network_resources"].pop("l2_interfaces", None)

        params = utils.remove_empties(
            l2_interfaces_parser.validate_config(
                self.argument_spec,
                {"config": objs},
                redact=True,
            ),
        )

        facts["l2_interfaces"] = params.get("config", [])
        ansible_facts["ansible_network_resources"].update(facts)

        return ansible_facts

    def _flatten_vlans(self, data):
        """
        Flatten the vlan lines if it also contains lines that mention 'switchport trunk allowed vlan add'
        as we will merge all the entries in a list
        :param obj: data
        :returns: flattened vlan entries as switchport trunk allowed vlan
        """
        lines = data.split("\n")
        vlans = ""
        cur_indent = 0
        result = []
        regex_vlan_special_case = re.compile(
            r"\s+switchport\strunk\sallowed\svlan\s(none|all|except|remove)",
        )
        regex_vlan_add_line = re.compile(r"\s+switchport\strunk\sallowed\svlan\sadd")
        regex_vlan_set_line = re.compile(r"\s+switchport\strunk\sallowed\svlan")

        for line in lines:
            # If line starts with one of these entries, that is special one liner entry
            if regex_vlan_special_case.match(line):
                result.append(line)

            # If line starts with  allowed vlan add
            elif regex_vlan_add_line.match(line):
                if vlans:
                    vlans += "," + line.rsplit("add", maxsplit=1)[-1].strip()
                else:
                    vlans = line.rsplit("add", maxsplit=1)[-1].strip()
                cur_indent = len(line) - len(line.lstrip())

            # If line starts only with allowed vlan
            elif regex_vlan_set_line.match(line):
                vlans = line.rsplit("vlan", maxsplit=1)[-1].strip()
                cur_indent = len(line) - len(line.lstrip())

            else:
                if vlans:
                    result.append(f"{' ' * cur_indent}switchport trunk allowed vlan {vlans}")
                    vlans = ""
                result.append(line)

        if vlans:
            result.append(f"{' ' * cur_indent}switchport trunk allowed vlan {vlans}")

        return "\n".join(result)
