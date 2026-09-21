"""Pure validation of explicit teaching links; no inference from prose."""


def ordered_steps(steps, selected):
    by_id = {step.step_id: step for step in steps}
    result, visiting, visited = [], set(), set()

    for key in selected:
        stack = [(key, False)]
        while stack:
            current, finishing = stack.pop()
            if finishing:
                visiting.remove(current)
                visited.add(current)
                result.append(by_id[current])
                continue
            if current in visited:
                continue
            if current in visiting or current not in by_id:
                raise ValueError("invalid teaching prerequisite")
            visiting.add(current)
            stack.append((current, True))
            stack.extend(
                (dependency, False) for dependency in reversed(by_id[current].prerequisite_step_ids)
            )
    return result


def teaching_links_valid(bundle):
    concepts = [item.concept_id for item in bundle.concepts.concepts]
    steps = [item.step_id for item in bundle.steps.steps]
    if len(concepts) != len(set(concepts)) or len(steps) != len(set(steps)):
        return False
    try:
        ordered_steps(bundle.steps.steps, steps)
    except ValueError:
        return False
    trees = {tree.id: {c.id for c in tree.causes} for tree in bundle.fault_trees.trees}
    components = {c.id for c in bundle.hardware.hardware.components}
    seen = set()
    for binding in bundle.steps.bindings:
        if (
            binding.cause_id not in trees.get(binding.tree_id, set())
            or binding.component_id not in components
            or not set(binding.concept_ids).issubset(concepts)
            or not set(binding.step_ids).issubset(steps)
            or not (binding.concept_ids or binding.step_ids)
        ):
            return False
        for values in (binding.levels, binding.concept_ids, binding.step_ids):
            if len(values) != len(set(values)):
                return False
        for level in binding.levels:
            identity = (binding.tree_id, binding.cause_id, binding.component_id, level)
            if identity in seen:
                return False
            seen.add(identity)
    return True
