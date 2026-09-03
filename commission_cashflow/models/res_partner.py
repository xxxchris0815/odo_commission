from odoo import api, fields, models


class CommissionAgentRole(models.Model):
    _name = "commission.agent.role"
    _description = "Commission role of an agent"
    _rec_name = "role"

    _unique_agent_role = models.Constraint(
        "UNIQUE(agent_id, role)",
        "An agent can only have one commission per role.",
    )

    agent_id = fields.Many2one(
        comodel_name="res.partner",
        required=True,
        ondelete="cascade",
        domain="[('agent', '=', True)]",
    )
    role = fields.Selection(
        [
            ("closer", "Closer"),
            ("opener", "Opener"),
        ],
        required=True,
    )
    commission_id = fields.Many2one(
        comodel_name="commission",
        required=True,
        ondelete="restrict",
    )

    def _sync_partner_default_commission(self):
        for rec in self.filtered(lambda r: r.role == "closer" and r.agent_id):
            rec.agent_id.commission_id = rec.commission_id

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_partner_default_commission()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._sync_partner_default_commission()
        return res


class ResPartner(models.Model):
    _inherit = "res.partner"

    commission_role_ids = fields.One2many(
        comodel_name="commission.agent.role",
        inverse_name="agent_id",
        string="Commission Roles",
        help="An agent can be Closer, Opener, or both. Each role has its own "
        "commission rule. On a deal, the same person can be added once per role.",
    )

    def get_commission_for_role(self, role):
        self.ensure_one()
        role_line = self.commission_role_ids.filtered(lambda r: r.role == role)[:1]
        if role_line:
            return role_line.commission_id
        if role == "closer":
            return self.commission_id
        return self.env["commission"]
