"""Lossless aliases of equal sanitized fields; source/condition units stay whole."""
from app.ai.output_contract import project_explanation_state

PROVIDER_PROJECTION_VERSION = "explanation-input-v1"


def explanation_input(payload):
    result = payload.model_dump(mode="json")
    state = project_explanation_state(payload.workflow_state)
    aliases = {}
    for duplicate, canonical in (("sensor_values", "sensor_data"),
                                 ("possible_causes", "reasoned_causes")):
        if duplicate in state and canonical in state and state[duplicate] == state[canonical]:
            aliases[duplicate] = canonical
            del state[duplicate]
    if aliases:
        state["field_aliases"] = aliases
    result["workflow_state"] = state
    return result


def without_schema_titles(value):
    """Only JSON Schema annotation titles are removed, not property names."""
    if isinstance(value, list):
        return [without_schema_titles(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: ({name: without_schema_titles(schema) for name, schema in item.items()}
                  if key in {"properties", "$defs"} else without_schema_titles(item))
            for key, item in value.items() if key != "title"}
