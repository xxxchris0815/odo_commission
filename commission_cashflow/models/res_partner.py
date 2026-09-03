from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    agent_role = fields.Selection(
        [
            ("closer", "Closer"),
            ("opener", "Opener"),
        ],
        string="Agent Role",
        help="Closer: earns commission on the cashflow of their own deals. "
        "Opener: earns commission on deals originated from appointments they set.",
    )
