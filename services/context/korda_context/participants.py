"""Authority comes from operator enrollment, independently of phone identity."""


def normalize_roles(value: str | list[str]) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if (not isinstance(values, list) or not values
            or any(not isinstance(role, str) or not role.strip() for role in values)):
        raise ValueError("registered participant roles must be nonempty strings")
    return list(dict.fromkeys(role.strip() for role in values))


def registered_roles(participant: dict) -> list[str]:
    if not isinstance(participant.get("id"), str) or not participant["id"].strip():
        raise ValueError("registered participant identity and roles are required")
    roles = normalize_roles(participant.get("roles", participant.get("role")))
    if "role" in participant and participant["role"] != roles[0]:
        raise ValueError("registered participant primary role must match its roles")
    return roles
