{
    "name": "Commission on Cashflow",
    "version": "19.0.1.1.0",
    "summary": "Settle commissions based on actual payment receipts, "
    "supports partial payments and Closer/Opener agent roles.",
    "author": "Custom",
    "license": "AGPL-3",
    "category": "Sales Management",
    "depends": ["account_commission_oca"],
    "data": [
        "views/res_partner_views.xml",
        "views/account_move_views.xml",
        "wizards/commission_make_settle_views.xml",
    ],
    "installable": True,
}
