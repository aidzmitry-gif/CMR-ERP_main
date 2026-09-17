from config.access import (
    allowed_slugs,
    is_package_allowed,
    is_role_allowed_for_department,
    is_slug_allowed,
    is_super,
    user_by_username,
    users_with_titles,
)


def test_department_role_gate_is_fail_closed_for_unknown_combinations():
    assert is_role_allowed_for_department("Продажи", "sales") is True
    assert is_role_allowed_for_department("Продажи", "finance") is False
    assert is_role_allowed_for_department("Нет такого отдела", "sales") is False


def test_access_helpers_combine_roles_and_keep_super_roles_global():
    assert allowed_slugs(["sales", "procurement"]) >= {"crm", "procurement"}
    assert is_super(["sales", "director"]) is True
    assert is_super(["sales"]) is False
    assert is_slug_allowed("crm", ["sales"]) is True
    assert is_slug_allowed("finance", ["sales"]) is False
    assert is_slug_allowed("finance", ["commercial"]) is True
    assert is_package_allowed("not-a-module", ["sales"]) is True
    assert is_package_allowed("finance", ["sales"]) is False


def test_user_registry_and_role_titles_are_stable():
    assert user_by_username("makarov")["role"] == "sales"
    assert user_by_username("missing") is None
    users = users_with_titles()
    director = next(user for user in users if user["username"] == "kharkovich_d")
    assert director["role_title"] == "Директор"
    assert all(user.get("full_name") and user.get("role_title") for user in users)
