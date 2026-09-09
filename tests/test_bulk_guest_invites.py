from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bulk_guest_invites_are_owner_only_and_read_only_against_langame():
    src = (ROOT / "app/webapp/guest_invites_api.py").read_text(encoding="utf-8")
    assert '@router.post("/guest/invites/bulk")' in src
    assert 'user.role != UserRole.OWNER.value' in src
    assert "langame_client.guests_search(page=page, size=PAGE_SIZE)" in src
    assert "GuestLinkToken" in src
    assert "secrets.token_urlsafe(32)" in src
    assert "await write_audit" in src
    assert "https://t.me/{bot_username}?start=guest_{token_row.token}" in src


def test_bulk_invites_do_not_create_duplicates_or_reinvite_linked_guests():
    src = (ROOT / "app/webapp/guest_invites_api.py").read_text(encoding="utf-8")
    assert "GuestTelegram.guest_id.in_(local_ids)" in src
    assert "GuestLinkToken.guest_id.in_(local_ids)" in src
    assert "GuestLinkToken.used_at.is_(None)" in src
    assert "GuestLinkToken.expires_at > now" in src
    assert "already_linked += 1" in src
    assert "reused += 1" in src


def test_owner_bulk_invite_surface_is_loaded_without_changing_unified_navigation_owner():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    design = (ROOT / "app/webapp/static/design-v2.js").read_text(encoding="utf-8")
    assert "guest_invites_router" in main
    assert main.index("web_app.include_router(guest_invites_router)") < main.index("web_app.include_router(unified_api_router)")
    assert "guest-invites.js" in design
    assert "smm-actions.js" in design
