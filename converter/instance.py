import copy
from converter import utils
from . import base, group
from .context import context
from .config import config
from sketchformat.layer_group import SymbolInstance, OverrideValue
from sketchformat.style import Style
from typing import Optional, List, Tuple


def convert(fig_instance):
    if fig_instance["symbolData"]["symbolID"][0] == 4294967295:
        # Broken instance, return a placeholder in its place
        utils.log_conversion_warning("SYM001", fig_instance)
        return group.convert(fig_instance)

    all_overrides = get_all_overrides(fig_instance)
    sketch_overrides, unsupported = convert_overrides(all_overrides)
    if unsupported:
        if config.can_detach:
            utils.log_conversion_warning("SYM003", fig_instance, props=unsupported)

            # Modify input tree in place, with the detached symbol subtree
            detach_symbol(fig_instance, all_overrides)
            return group.convert(fig_instance)
        else:
            utils.log_conversion_warning("SYM002", fig_instance, props=unsupported)

    # Use always the GUID of the master for the symbolID
    # The instance symbolID can refer to the overrideKey instead
    fig_master = context.find_symbol(fig_instance["symbolData"]["symbolID"])
    obj = SymbolInstance(
        **base.base_styled(fig_instance),
        symbolID=utils.gen_object_id(fig_master["guid"]),
        overrideValues=sketch_overrides,
    )
    # Replace style
    obj.style = Style(do_objectID=utils.gen_object_id(fig_instance["guid"], b"style"))

    return obj


def post_process(fig_instance, sketch_instance):
    if sketch_instance._class == "group":
        return group.post_process_frame(fig_instance, sketch_instance)
    else:
        return sketch_instance


def master_instance(fig_symbol):
    obj = SymbolInstance(
        **base.base_styled(fig_symbol),
        symbolID=utils.gen_object_id(fig_symbol["guid"]),
    )
    obj.do_objectID = utils.gen_object_id(fig_symbol["guid"], b"master_instance")

    # Replace style
    obj.style = Style(
        do_objectID=utils.gen_object_id(fig_symbol["guid"], b"master_instance_style")
    )

    return obj


def convert_overrides(all_overrides):
    sketch_overrides = []
    unsupported_overrides = []
    for override in all_overrides:
        sk, us = convert_override(override)
        sketch_overrides += sk
        unsupported_overrides += us

    return sketch_overrides, unsupported_overrides


def get_all_overrides(fig_instance):
    """Gets all overrides of a symbol, including component assignments"""

    # Convert top-level properties to overrides
    fig_master = context.find_symbol(fig_instance["symbolData"]["symbolID"])
    all_overrides = convert_properties_to_overrides(
        fig_master, fig_instance.get("componentPropAssignments", [])
    )

    # Sort overrides by length of path. This ensures top level overrides are processed before
    # nested ones which is required because a top override may change the symbol instance that is
    # used by child overrides
    for override in sorted(
        fig_instance["symbolData"]["symbolOverrides"],
        key=lambda x: len(x["guidPath"]["guids"]),
    ):
        guid_path = override["guidPath"]["guids"]
        new_override = {"guidPath": override["guidPath"]}
        for prop, value in override.items():
            if prop == "componentPropAssignments":
                nested_master = find_symbol_master(fig_master, guid_path, all_overrides)
                all_overrides += convert_properties_to_overrides(nested_master, value, guid_path)
            else:
                new_override[prop] = value

        all_overrides.append(new_override)

    return all_overrides


def convert_override(override: dict) -> Tuple[List[OverrideValue], List[str]]:
    sketch_overrides = []
    unsupported_overrides = []

    # Convert uuids in the path from top symbol to child instance
    sketch_path = [utils.gen_object_id(guid) for guid in override["guidPath"]["guids"]]
    sketch_path_str = "/".join(sketch_path)

    for prop, value in override.items():
        if prop == "guidPath":
            continue
        if prop == "textData":
            # Text override.
            if "styleOverrideTable" in value:
                unsupported_overrides.append("textData.styleOverrideTable")
                continue

            sketch_overrides.append(
                OverrideValue(
                    overrideName=f"{sketch_path_str}_stringValue",
                    value=value["characters"],
                )
            )
        elif prop == "overriddenSymbolID":
            sketch_overrides.append(
                OverrideValue(
                    overrideName=f"{sketch_path_str}_symbolID",
                    value=utils.gen_object_id(value),
                )
            )
        elif prop in ["size", "pluginData", "name", "exportSettings"]:
            # Size is handled by applying derivedSymbolData
            # The rest are surely not worth detaching for
            pass
        else:
            # Unknown override
            unsupported_overrides.append(prop)

    return sketch_overrides, unsupported_overrides


def find_symbol_master(root_symbol, guid_path, overrides):
    current_symbol = root_symbol
    path = []
    for guid in guid_path:
        path.append(guid)
        # See if we have overriden the symbol_id
        symbol_id = [
            o["overriddenSymbolID"]
            for o in overrides
            if o["guidPath"]["guids"] == path and "overriddenSymbolID" in o
        ]
        if symbol_id:
            symbol_id = symbol_id[0]
        else:
            # Otherwise, find the instance
            instance = context.fig_node(guid)
            symbol_id = instance["symbolData"]["symbolID"]

        current_symbol = context.find_symbol(symbol_id)

    return current_symbol


def convert_properties_to_overrides(fig_master, properties, guid_path=[]):
    """Convert .fig property assignments to overrides.
    This makes it easier to work with them in a unified way."""
    overrides = []

    for prop in properties:
        for (ref_prop, ref_guid) in find_refs(fig_master, prop["defID"]):
            if ref_prop["componentPropNodeField"] == "OVERRIDDEN_SYMBOL_ID":
                override = {"overriddenSymbolID": prop["value"]["guidValue"]}
            elif ref_prop["componentPropNodeField"] == "TEXT_DATA":
                override = {"textData": prop["value"]["textValue"]}
            elif ref_prop["componentPropNodeField"] == "VISIBLE":
                override = {"visible": prop["value"]["boolValue"]}
            else:  # INHERIT_FILL_STYLE_ID
                raise Exception(f"Unexpected property {ref_prop['componentPropNodeField']}")

            overrides.append({**override, "guidPath": {"guids": guid_path + [ref_guid]}})

    return overrides


def find_refs(node, ref_id):
    """Find all usages of a property in a symbol, recursively"""
    refs = [
        (ref, node["guid"])
        for ref in node.get("componentPropRefs", [])
        if ref["defID"] == ref_id and not ref["isDeleted"]
    ]

    for ch in node.get("children", []):
        refs += find_refs(ch, ref_id)

    return refs


def detach_symbol(fig_instance, all_overrides):
    # Find symbol master
    fig_master = context.fig_node(fig_instance["symbolData"]["symbolID"])
    detached_children = copy.deepcopy(fig_master["children"], {})

    # Apply overrides to children
    for c in detached_children:
        apply_overrides(c, fig_instance["guid"], all_overrides, fig_instance["derivedSymbolData"])

    fig_instance["children"] = detached_children


def apply_overrides(fig_node, instance_id, overrides, derived_symbol_data):
    guid = fig_node.get("overrideKey", fig_node["guid"])

    # Apply overrides
    child_overrides = []
    for override in overrides:
        guids = override["guidPath"]["guids"]
        if guids[0] != guid:
            continue
        if len(guids) > 1:
            child_overrides.append({**override, "guidPath": {"guids": guids[1:]}})
        else:
            for k, v in override.items():
                if k == "guidPath":
                    continue
                elif k == "overriddenSymbolID":
                    fig_node["symbolData"]["symbolID"] = v
                else:
                    fig_node[k] = v

    # Recalculate size
    child_derived_data = []
    for derived in derived_symbol_data:
        guids = derived["guidPath"]["guids"]
        if guids[0] != guid:
            continue
        if len(guids) > 1:
            child_derived_data.append({**derived, "guidPath": {"guids": guids[1:]}})
        else:
            if "size" in derived:
                fig_node["size"] = derived["size"]
            if "transform" in derived:
                fig_node["transform"] = derived["transform"]

    # Generate a unique ID by concatenating instance_id + node_id
    fig_node["guid"] = tuple(j for i in (instance_id, guid) for j in i)

    # If it's an instance, pass the overrides down. Otherwise, convert the children
    if fig_node["type"] == "INSTANCE":
        fig_node["symbolData"]["symbolOverrides"] += child_overrides
        fig_node["derivedSymbolData"] += child_derived_data
    else:
        for c in fig_node.get("children", []):
            apply_overrides(c, instance_id, overrides, derived_symbol_data)
