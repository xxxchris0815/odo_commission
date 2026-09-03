{
    "name": "Commission on Cashflow",
    "version": "19.0.1.2.0",
    "summary": "Settle commissions based on actual payment receipts. "
    "Agents can hold Closer and Opener roles on the same deal.",
    "author": "Custom",
    "license": "AGPL-3",
    "category": "Sales Management",
    "depends": ["account_commission_oca"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_partner_views.xml",
        "views/account_move_views.xml",
        "wizards/commission_make_settle_views.xml",
    ],
    "installable": True,
}
