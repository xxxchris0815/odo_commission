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
    opener_commission_id = fields.Many2one(
        comodel_name="commission",
        string="Opener Commission",
        help="Used when this agent closed the deal and also set the appointment. "
        "The closer commission plus this opener commission are both applied.",
    )
