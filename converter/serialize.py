import json
from dataclasses import asdict, is_dataclass


def clean_obj(items):
    return {
        # Remove _ suffix for reserved keywords
        k[:-1] if k.endswith('_') else k: v
        for (k, v) in items
        # Skip optional fields that are not present
        if v is not None
    }


def convert_object(obj):
    if is_dataclass(obj):
        return asdict(obj, dict_factory=clean_obj)
    else:
        return obj.to_json()


def serialize(obj, path):
    return json.dump(
        obj,
        open(path, 'w'),
        default=convert_object,
        ensure_ascii=False,  # Write emoji directly, without surrogate pairs
        indent=2  # Makes debugging nicer. TODO: Remove
    )
