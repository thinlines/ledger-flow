from __future__ import annotations

from .config_service import AppConfig
from .institution_registry import canonical_template_id, display_name_for


def import_mode_for_account(account_cfg: dict) -> str:
    return "custom" if str(account_cfg.get("import_profile_id") or "").strip() else "institution"


def import_source_summary(config: AppConfig, account_cfg: dict) -> dict:
    profile_id = str(account_cfg.get("import_profile_id") or "").strip()
    if profile_id:
        profile_cfg = config.import_profiles.get(profile_id, {})
        return {
            "mode": "custom",
            "profile_id": profile_id,
            "institution_id": None,
            "display_name": str(profile_cfg.get("display_name") or "Custom CSV"),
            "profile": profile_cfg,
        }

    institution_id = canonical_template_id(account_cfg.get("institution")) or account_cfg.get("institution")
    return {
        "mode": "institution",
        "profile_id": None,
        "institution_id": institution_id,
        "display_name": display_name_for(institution_id, fallback=str(institution_id)) if institution_id else None,
        "profile": config.institution_templates.get(institution_id or "", {}),
    }


def resolve_import_source(config: AppConfig, account_cfg: dict) -> dict:
    summary = import_source_summary(config, account_cfg)
    if summary["mode"] == "custom":
        profile_id = str(summary["profile_id"] or "").strip()
        if not profile_id:
            raise ValueError("Custom import account is missing a profile id")
        if profile_id not in config.import_profiles:
            raise ValueError(f"Unknown import profile: {profile_id}")
        return summary

    institution_id = str(summary["institution_id"] or "").strip()
    if not institution_id:
        raise ValueError("Import account has no institution configured")
    if institution_id not in config.institution_templates:
        raise ValueError(f"Unknown institution template: {institution_id}")
    return summary
