import sop


def test_revenue_and_ar_means_chow():
    assert sop.parent_move_action({"lifetime_revenue": 84000, "outstanding_ar": 12400}) == "chow"


def test_revenue_without_ar_means_reparent():
    assert sop.parent_move_action({"lifetime_revenue": 47000, "outstanding_ar": 0}) == "reparent"


def test_ar_without_revenue_means_reparent():
    assert sop.parent_move_action({"lifetime_revenue": 0, "outstanding_ar": 500}) == "reparent"


def test_no_billing_means_reparent():
    assert sop.parent_move_action({"lifetime_revenue": 0, "outstanding_ar": 0}) == "reparent"
    assert sop.parent_move_action({"lifetime_revenue": None, "outstanding_ar": ""}) == "reparent"
