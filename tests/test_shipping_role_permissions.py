"""Canonical business roles can enter shipping work without becoming reviewers."""
import pytest

from core.runtime.app import create_app
from core.services.auth import CurrentUser, has_permission


@pytest.fixture(scope="module")
def shipping_core():
    return create_app().state.core


@pytest.mark.parametrize("role", ["sales_head", "sales", "sales_manager", "sales_cli"])
def test_sales_can_prepare_owned_orders_without_office_assignment_authority(shipping_core, role):
    user = CurrentUser("sales-operator", [role])
    assert has_permission(shipping_core, user, "sales.shipping.associate")
    assert not has_permission(shipping_core, user, "office.shipping.review.assign")
    assert not has_permission(shipping_core, user, "office.shipping.review.revoke")


@pytest.mark.parametrize("role,can_associate,can_resolve", [
    ("assistant", False, False), ("finance", True, True),
])
def test_office_roles_still_require_individual_reviewer_assignment(shipping_core, role, can_associate, can_resolve):
    user = CurrentUser("office-operator", [role])
    assert has_permission(shipping_core, user, "office.doc.read")
    assert has_permission(shipping_core, user, "office.carrier.request")
    assert has_permission(shipping_core, user, "office.shipping.associate") == can_associate
    assert has_permission(shipping_core, user, "logistics.intake.resolve") == can_resolve
    assert not has_permission(shipping_core, user, "office.shipping.review.assign")
    assert not has_permission(shipping_core, user, "office.shipping.review.revoke")


@pytest.mark.parametrize("role", ["warehouse", "hr", "procurement", "onboarding"])
def test_unrelated_module_access_does_not_grant_shipping_confirmation(shipping_core, role):
    user = CurrentUser("other-operator", [role])
    for permission in ("sales.shipping.associate", "office.shipping.associate",
                       "office.shipping.review.assign", "logistics.intake.resolve"):
        assert not has_permission(shipping_core, user, permission)
