{
    "name": "Commission on Cashflow",
    "version": "19.0.1.6.0",
    "summary": "Settle commissions based on actual payment receipts. "
    "Invoice lines can have Opener, Closer and Partner roles.",
    "author": "Custom",
    "license": "AGPL-3",
    "category": "Sales Management",
    "depends": ["account_commission_oca"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_partner_views.xml",
        "views/account_move_views.xml",
        "wizards/commission_make_settle_views.xml",
        "wizards/cashflow_week_report_views.xml",
    ],
    "installable": True,
}
