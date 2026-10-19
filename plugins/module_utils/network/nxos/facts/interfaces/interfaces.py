# -*- coding: utf-8 -*-
# Copyright 2025 Red Hat
# GNU General Public License v3.0+
# (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function


__metaclass__ = type

"""
The nxos interfaces fact class
It is in this file the configuration is collected from the device
for a given resource, parsed, and the facts tree is populated
based on the configuration.
"""

from ansible_collections.ansible.netcommon.plugins.module_utils.network.common import (
    utils,
)

from ansible_collections.cisco.nxos.plugins.module_utils.network.nxos.argspec.interfaces.interfaces import (
    InterfacesArgs,
)
from ansible_collections.cisco.nxos.plugins.module_utils.network.nxos.rm_templates.interfaces import (
    InterfacesTemplate,
)


class InterfacesFacts(object):
    """The nxos interfaces facts class"""

    def __init__(self, module, subspec="config", options="options"):
        self._module = module
        self.argument_spec = InterfacesArgs.argument_spec

    def _get_interface_config(self, connection):
        return connection.get("show running-config | section ^interface")

    def _get_interface_config_with_defaults(self, connection):
        return connection.get("show running-config all | section ^interface")

    def populate_facts(self, connection, ansible_facts, data=None):
        """Populate the facts for Interfaces network resource

        :param connection: the device connection
        :param ansible_facts: Facts dictionary
        :param data: previously collected conf

        :rtype: dictionary
        :returns: facts
        """
        facts = {}
        objs = []
        from_device = data is None

        if not data:
            data = self._get_interface_config(connection)

        # parse native config using the Interfaces template
        interfaces_parser = InterfacesTemplate(lines=data.splitlines(), module=self._module)
        parsed = interfaces_parser.parse()
        if from_device and any("enabled" not in obj for obj in parsed.values()):
            # NX-OS omits implicit shutdown/no shutdown. Read the effective state
            # from the device instead of guessing platform, mode or type defaults.
            # Only supplement enabled: importing other defaults would change the
            # removal semantics of replaced/overridden for unrelated attributes.
            default_lines = self._get_interface_config_with_defaults(connection).splitlines()
            enabled_parser = InterfacesTemplate(
                lines=[
                    line
                    for line in default_lines
                    if line.startswith("interface ") or line.strip() in ("shutdown", "no shutdown")
                ],
                module=self._module,
            )
            enabled_by_name = enabled_parser.parse()
            for name, obj in parsed.items():
                enabled = enabled_by_name.get(name, {}).get("enabled")
                if "enabled" not in obj and enabled is not None:
                    obj["enabled"] = enabled

        objs = list(parsed.values())
        ansible_facts["ansible_network_resources"].pop("interfaces", None)
        facts = {"interfaces": []}
        params = utils.remove_empties(
            interfaces_parser.validate_config(self.argument_spec, {"config": objs}, redact=True),
        )

        facts["interfaces"] = params["config"]
        ansible_facts["ansible_network_resources"].update(facts)

        return ansible_facts
