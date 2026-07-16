from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any


@lru_cache(maxsize=1)
def organization_taxonomy() -> dict[str, Any]:
    resource = files("jobpicky.resources").joinpath("organization_groups_v1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def organization_options() -> list[dict[str, str]]:
    return [{"value": group["id"], "label": group["label"]} for group in organization_taxonomy()["groups"]]


def organization_aliases() -> dict[str, list[str]]:
    return {
        organization["name"]: list(organization.get("aliases", []))
        for organization in organization_taxonomy()["organizations"]
    }


def organization_groups() -> dict[str, dict[str, Any]]:
    organizations = organizations_by_id()
    groups: dict[str, dict[str, Any]] = {}
    for source in organization_taxonomy()["groups"]:
        group = dict(source)
        group["member_names"] = [
            organizations[member_id]["name"]
            for member_id in group.get("members", [])
            if member_id in organizations
        ]
        groups[group["id"]] = group
    return groups


def organizations_by_id() -> dict[str, dict[str, Any]]:
    return {organization["id"]: organization for organization in organization_taxonomy()["organizations"]}
